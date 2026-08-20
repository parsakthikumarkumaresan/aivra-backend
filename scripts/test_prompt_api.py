import asyncio
from httpx import AsyncClient
from app.main import app

async def main():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # 1. Login
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "demo@aivra-demo.com", "password": "demo1234"}
        )
        print("Login Status:", login_res.status_code)
        token_data = login_res.json()
        token = token_data["accessToken"]
        org_id = token_data["organizationId"]
        print("Token Org ID:", org_id)

        # 2. Get Screening Prompt
        candidate_id = "cand_01m0f2ke9zffn79pem3jpsckwf"
        prompt_res = await client.get(
            f"/api/v1/hr/screenings/candidates/{candidate_id}/prompt",
            headers={"Authorization": f"Bearer {token}"}
        )
        print("Prompt API Status:", prompt_res.status_code)
        print("Prompt API Response:", prompt_res.text)

if __name__ == "__main__":
    asyncio.run(main())
