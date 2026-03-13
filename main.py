import uvicorn
from dotenv import load_dotenv
load_dotenv()

from app.config import settings

if __name__ == "__main__":
    uvicorn.run("app.api:app", host=settings.HOST, port=settings.PORT, reload=False)
