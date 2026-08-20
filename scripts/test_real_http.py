import asyncio
import httpx

async def main():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001/api/v1") as client:
        # Login
        r = await client.post("/auth/login", json={"email": "demo@aivra-demo.com", "password": "demo1234"})
        print("Login status:", r.status_code)
        data = r.json()
        token = data["accessToken"]
        
        # Call prompt route
        pr = await client.get(
            "/hr/screenings/candidates/cand_01m0f2ke9zffn79pem3jpsckwf/prompt",
            headers={"Authorization": f"Bearer {token}"}
        )
        print("Prompt Status:", pr.status_code)
        print("Prompt Response:", pr.text)

if __name__ == "__main__":
    asyncio.run(main())
