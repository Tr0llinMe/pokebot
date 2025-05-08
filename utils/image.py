import os
import requests
from PIL import Image, ImageDraw, ImageFont
import io

def normalize_pokeapi_name(archetype_name: str) -> str:
    # Convert "RoaringMoon" or "Iron Valiant" to "roaring-moon"
    # Handles camel case and spaces
    name = archetype_name.replace(" ", "-")
    # Insert hyphens before uppercase letters (except the first)
    name = ''.join(['-' + c.lower() if c.isupper() and i != 0 else c.lower() for i, c in enumerate(name)])
    name = name.replace('--', '-')  # In case of double hyphens
    return name

def get_sprite(archetype_name: str) -> Image.Image:
    sprite_dir = './assets/sprites'
    os.makedirs(sprite_dir, exist_ok=True)
    sprite_path = os.path.join(sprite_dir, f'{archetype_name.lower()}.png')
    
    # Special case for "Others" archetype - use Unown
    if archetype_name == "Others":
        sprite_path = os.path.join(sprite_dir, 'unown.png')
        if os.path.exists(sprite_path):
            return Image.open(sprite_path).convert('RGBA')
        # Fetch Unown sprite if not cached
        url = 'https://pokeapi.co/api/v2/pokemon/unown/'
        try:
            data = requests.get(url).json()
            sprite_url = data['sprites']['front_default']
            if not sprite_url:
                raise Exception("No sprite found in API response.")
            sprite_data = requests.get(sprite_url).content
            with open(sprite_path, 'wb') as f:
                f.write(sprite_data)
            return Image.open(io.BytesIO(sprite_data)).convert('RGBA')
        except Exception as e:
            print(f'Error fetching Unown sprite: {e}')
            return Image.new('RGBA', (64, 64), (255, 255, 255, 0))
    
    if os.path.exists(sprite_path):
        return Image.open(sprite_path).convert('RGBA')
    
    # Try to fetch from PokéAPI
    pokeapi_name = normalize_pokeapi_name(archetype_name)
    url = f'https://pokeapi.co/api/v2/pokemon/{pokeapi_name}/'
    try:
        data = requests.get(url).json()
        sprite_url = data['sprites']['front_default']
        if not sprite_url:
            raise Exception("No sprite found in API response.")
        sprite_data = requests.get(sprite_url).content
        with open(sprite_path, 'wb') as f:
            f.write(sprite_data)
        return Image.open(io.BytesIO(sprite_data)).convert('RGBA')
    except Exception as e:
        print(f'Error fetching sprite for {archetype_name}: {e}')
        # Return a blank placeholder
        return Image.new('RGBA', (64, 64), (255, 255, 255, 0))

def winrate_color(winrate: float) -> tuple:
    # Interpolate between red (low), white (mid), blue (high)
    if winrate < 40:
        # Red: (255, 128, 128)
        return (255, int(128 + (winrate/40)*127), int(128 + (winrate/40)*127))
    elif winrate > 60:
        # Blue: (128, 192, 255)
        return (int(128 + ((100-winrate)/40)*127), int(192 + ((100-winrate)/40)*63), 255)
    else:
        # White: (255, 255, 255)
        return (255, 255, 255)

def create_matchup_image(summary: dict, archetype_name: str) -> Image.Image:
    cell_width, cell_height = 120, 180
    try:
        font = ImageFont.truetype('arial.ttf', 16)
    except:
        # Fallback to default font if arial not found
        font = ImageFont.load_default()
    
    num_cells = len(summary)
    if num_cells == 0:
        return None
        
    img = Image.new('RGBA', (cell_width * num_cells, cell_height), (255,255,255,255))
    draw = ImageDraw.Draw(img)
    
    for i, (opp, record) in enumerate(summary.items()):
        total = record['Win'] + record['Loss'] + record['Tie']
        if total == 0:
            continue
            
        winrate = (record['Win'] + record['Tie']/3) / total * 100
        color = winrate_color(winrate)
        x = i * cell_width
        
        # Draw background
        draw.rectangle([x, 0, x+cell_width, cell_height], fill=color)
        
        # Draw sprite
        sprite = get_sprite(opp)
        sprite = sprite.resize((64, 64))
        img.paste(sprite, (x + 28, 20), sprite)
        
        # Draw text
        text_color = (0, 0, 0)  # Black text
        draw.text((x+10, 90), f'{winrate:.1f}%', font=font, fill=text_color)
        draw.text((x+10, 120), f'{record["Win"]}-{record["Loss"]}-{record["Tie"]}', font=font, fill=text_color)
        
        # Handle archetype name with better text wrapping
        # Split camelCase: look for capital letters after lowercase
        name_parts = []
        current_word = opp[0]
        for c in opp[1:]:
            if c.isupper() and current_word[-1].islower():
                name_parts.append(current_word)
                current_word = c
            else:
                current_word += c
        name_parts.append(current_word)
        
        if len(name_parts) > 1:
            # For multi-part names (like RoaringMoon), split into parts
            first_line = name_parts[0]
            second_line = ''.join(name_parts[1:])
            draw.text((x+10, 140), first_line, font=font, fill=text_color)
            draw.text((x+10, 155), second_line, font=font, fill=text_color)
        else:
            # For single-word names
            draw.text((x+10, 140), opp, font=font, fill=text_color)
    
    return img 