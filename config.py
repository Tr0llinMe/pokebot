from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_TYPE = 'mysql+pymysql'
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_NAME = os.getenv('DB_NAME')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URI = f'{DATABASE_TYPE}://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
OWNER_ID = os.getenv('OWNER_ID')
