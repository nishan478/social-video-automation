import json
import os
from urllib.parse import quote

import boto3
import requests
from botocore.config import Config


def env(name, default=""):
    return (os.getenv(name, default) or "").strip().strip('"').strip("'")


def require(*names):
    missing = [name for name in names if not env(name)]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): " + ", ".join(missing)
        )


def r2_client():
    require(
        "R2_ENDPOINT",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
    )

    return boto3.client(
        service_name="s3",
        endpoint_url=env("R2_ENDPOINT").rstrip("/"),
        aws_access_key_id=env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def public_url_for_key(key: str) -> str:
    base = env("R2_PUBLIC_URL").rstrip("/")

    if not base:
        raise RuntimeError(
            "R2_PUBLIC_URL is required. Buffer needs a publicly accessible media URL."
        )

    return base + "/" + quote(
        key.lstrip("/"),
        safe="/-_.~",
    )


def gql(query: str):
    require("BUFFER_API_KEY")

    response = requests.post(
        "https://api.buffer.com",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {env('BUFFER_API_KEY')}",
        },
        json={"query": query},
        timeout=120,
    )

    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(
            f"Buffer returned non-JSON HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        ) from exc

    if response.status_code >= 400:
        raise RuntimeError(
            f"Buffer HTTP {response.status_code}: {data}"
        )

    if data.get("errors"):
        raise RuntimeError(
            "Buffer GraphQL error: "
            + json.dumps(data["errors"], ensure_ascii=False)
        )

    return data


def gql_string(value: str) -> str:
    return json.dumps(value)


def check_public_media(url: str):
    try:
        response = requests.get(
            url,
            headers={"Range": "bytes=0-0"},
            stream=True,
            timeout=60,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not reach the public video URL: {exc}"
        ) from exc

    if response.status_code not in (200, 206):
        raise RuntimeError(
            f"Public video URL returned HTTP "
            f"{response.status_code}: {url}"
        )

    content_type = (
        response.headers.get("Content-Type") or ""
    ).lower()

    if (
        content_type
        and "video" not in content_type
        and "octet-stream" not in content_type
    ):
        print(
            f"WARNING: public URL Content-Type is "
            f"{content_type!r}; Buffer may reject unsupported media."
        )
