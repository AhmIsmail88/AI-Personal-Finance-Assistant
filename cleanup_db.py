import asyncio
from sqlalchemy import text
from app.database.connection import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM income WHERE id = 2"))
        await session.commit()
        print("Done")

if __name__ == "__main__":
    asyncio.run(main())
