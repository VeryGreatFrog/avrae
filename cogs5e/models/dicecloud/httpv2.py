import asyncio
import json
import logging
import dateutil.parser as dtparser
import datetime.utcnow

import aiohttp

from .errors import Forbidden, HTTPException, NotFound, Timeout

MAX_TRIES = 10
log = logging.getLogger(__name__)


class DicecloudHTTP:
    def __init__(self, api_base, username, password, debug=False):
        self.base = api_base
        self.username = username
        self.password = password
        self.debug = debug
        self.auth_token = None
        self.user_id = None
        self.expiration = None

    async def request(self, method, endpoint, body, headers=None, query=None):
            
        if headers is None:
            headers = {}
        if query is None:
            query = {}

        if body is not None:
            if isinstance(body, str):
                headers["Content-Type"] = "text/plain"
            else:
                body = json.dumps(body)
                headers["Content-Type"] = "application/json"

        if self.debug:
            print(f"{method} {endpoint}: {body}")
        data = None
        async with aiohttp.ClientSession() as session:
            if not self.auth_token or self.expiration <= datetime.utcnow():
                await self.get_auth(session)
            headers["Authorization"] = "Bearer " + self.auth_token
            data = await self.try_until_max(session, endpoint, body, headers, query)

        return data
    
    async def try_until_max(method, session, endpoint, data, headers, params):
        for _ in range(MAX_TRIES):
            try:
                async with session.request(
                    method, f"{self.base}{endpoint}", data=data, headers=headers, params=params
                ) as resp:
                    log.info(f"Dicecloud V2 returned {resp.status} ({endpoint})")
                    if resp.status == 200:
                        return await resp.json(encoding="utf-8")
                    elif resp.status == 429:
                        timeout = await resp.json(encoding="utf-8")
                        log.warning(f"Dicecloud V2 ratelimit hit ({endpoint}) - resets in {timeout}ms")
                        await asyncio.sleep(timeout["timeToReset"] / 1000)  # rate-limited, wait and try again
                    elif 400 <= resp.status < 600:
                        if resp.status == 403:
                            raise Forbidden(resp.reason)
                        elif resp.status == 404:
                            raise NotFound(resp.reason)
                        else:
                            raise HTTPException(resp.status, resp.reason)
                    else:
                        log.warning(f"Unknown response from Dicecloud: {resp.status}")
            except aiohttp.ServerDisconnectedError:
                raise HTTPException(None, "Server disconnected")
        raise Timeout(f"Dicecloud failed to respond after {MAX_TRIES} tries. Please try again.") # we did 10 loops and never got 200, so we must have 429ed
    
    async def get_auth(self, session):
        data = self.try_until_max(session, "/login", {"username": self.username, "password": self.password})
        self.auth_token = data['token']
        self.user_id = data['id']
        self.expiration = dtparser.parse(data['tokenExpires']).timestamp()

    async def get(self, endpoint):
        return await self.request("GET", endpoint, None)

    async def post(self, endpoint, body):
        return await self.request("POST", endpoint, body)

    async def put(self, endpoint, body):
        return await self.request("PUT", endpoint, body)

    async def delete(self, endpoint):
        return await self.request("DELETE", endpoint, None)
