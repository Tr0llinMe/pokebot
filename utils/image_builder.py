import io
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont
import requests

class ImageBuilder:
    CARD_WIDTH = 146  # Standard Pokémon card width in pixels
    CARD_HEIGHT = 204  # Standard Pokémon card height in pixels
    PRIZE_WIDTH = 80   # Smaller width for prize cards
    PRIZE_HEIGHT = 112 # Smaller height for prize cards
    PADDING = 10  # Padding between cards
    TEXT_HEIGHT = 30  # Height for text area

    @classmethod
    def download_image(cls, url: str) -> Optional[Image.Image]:
        """Download an image from a URL or open a local file and return a PIL Image object."""
        try:
            # If the string looks like a local file path, open it directly
            if not (url.startswith('http://') or url.startswith('https://')):
                return Image.open(url)
            # Otherwise, treat as URL
            response = requests.get(url)
            response.raise_for_status()
            return Image.open(io.BytesIO(response.content))
        except Exception as e:
            print(f"Error downloading image from {url}: {str(e)}")
            return None

    @classmethod
    def card_name_placeholder(cls, name: str, width: int, height: int) -> Image.Image:
        """Generate a card-sized image with the card name as text."""
        image = Image.new('RGB', (width, height), 'lightgray')
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype('arial.ttf', 16)
        except:
            font = ImageFont.load_default()
        # Wrap text if too long
        lines = []
        words = name.split()
        line = ''
        for word in words:
            test_line = f'{line} {word}'.strip()
            # Use textbbox for compatibility
            try:
                bbox = draw.textbbox((0,0), test_line, font=font)
                test_width = bbox[2] - bbox[0]
            except AttributeError:
                test_width = font.getsize(test_line)[0]
            if test_width > width - 10:
                lines.append(line)
                line = word
            else:
                line = test_line
        lines.append(line)
        # Center text vertically
        total_height = 0
        line_heights = []
        for l in lines:
            try:
                bbox = draw.textbbox((0,0), l, font=font)
                h = bbox[3] - bbox[1]
            except AttributeError:
                h = font.getsize(l)[1]
            line_heights.append(h)
            total_height += h
        y = (height - total_height) // 2
        for idx, l in enumerate(lines):
            try:
                bbox = draw.textbbox((0,0), l, font=font)
                w = bbox[2] - bbox[0]
            except AttributeError:
                w = font.getsize(l)[0]
            x = (width - w) // 2
            draw.text((x, y), l, fill='black', font=font)
            y += line_heights[idx]
        return image

    @classmethod
    def create_hand_image(
        cls,
        hand_cards: List[str],
        prize_cards: List[str],
        mulligans: int,
        hand_basics: Optional[List[bool]] = None
    ) -> Optional[Image.Image]:
        """Create a composite image of the starting hand and prize cards.
        hand_basics: list of booleans indicating if each hand card is a Basic Pokémon.
        """
        # Calculate image dimensions
        width = (cls.CARD_WIDTH * 7) + (cls.PADDING * 8)  # 7 cards + padding
        height = (
            cls.CARD_HEIGHT + cls.PADDING * 2 + cls.PRIZE_HEIGHT + cls.PADDING + cls.TEXT_HEIGHT
        )

        # Create blank image
        image = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(image)

        # Download and paste hand cards (top row)
        y_offset = cls.PADDING
        for i, card_url in enumerate(hand_cards):
            x_offset = cls.PADDING + (i * (cls.CARD_WIDTH + cls.PADDING))
            card_img = None
            if isinstance(card_url, Image.Image):
                card_img = card_url
            elif card_url:
                card_img = cls.download_image(card_url)
            if not card_img:
                card_img = cls.card_name_placeholder("Unknown", cls.CARD_WIDTH, cls.CARD_HEIGHT)
            image.paste(card_img.resize((cls.CARD_WIDTH, cls.CARD_HEIGHT)), (x_offset, y_offset))
            # Draw red outline if this card is a Basic Pokémon
            if hand_basics and i < len(hand_basics) and hand_basics[i]:
                outline_rect = [
                    x_offset, y_offset,
                    x_offset + cls.CARD_WIDTH - 1, y_offset + cls.CARD_HEIGHT - 1
                ]
                draw.rectangle(outline_rect, outline="red", width=6)

        # Download and paste prize cards (bottom row, smaller)
        y_offset = cls.PADDING * 2 + cls.CARD_HEIGHT
        for i, card_url in enumerate(prize_cards):
            x_offset = cls.PADDING + (i * (cls.PRIZE_WIDTH + cls.PADDING))
            card_img = None
            if isinstance(card_url, Image.Image):
                card_img = card_url
            elif card_url:
                card_img = cls.download_image(card_url)
            if not card_img:
                # If card_url is a string, use it as the card name
                card_name = card_url if isinstance(card_url, str) else "Unknown"
                card_img = cls.card_name_placeholder(card_name, cls.PRIZE_WIDTH, cls.PRIZE_HEIGHT)
            image.paste(card_img.resize((cls.PRIZE_WIDTH, cls.PRIZE_HEIGHT)), (x_offset, y_offset))

        # Add mulligan text
        try:
            font = ImageFont.truetype('arial.ttf', 20)
        except:
            font = ImageFont.load_default()
        draw.text((cls.PADDING, height - cls.TEXT_HEIGHT), f"Mulligans: {mulligans}", fill="black", font=font)

        return image

    @classmethod
    def save_to_bytes(cls, image: Image.Image) -> io.BytesIO:
        """Save a PIL Image to a BytesIO object."""
        img_bytes = io.BytesIO()
        image.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes 