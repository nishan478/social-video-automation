import json
import os

from script.common import (
    check_public_media,
    env,
    gql,
    gql_string,
    public_url_for_key,
    r2_client,
    require,
)


VIDEO_EXTENSIONS = (
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
)


def find_next_video():
    client = r2_client()
    bucket = env("R2_BUCKET_NAME")

    response = client.list_objects_v2(
        Bucket=bucket,
        Prefix=env("R2_PREFIX"),
    )

    videos = []

    for item in response.get("Contents", []):
        key = item["Key"]

        if key.lower().endswith(VIDEO_EXTENSIONS):
            videos.append(key)

    if not videos:
        raise RuntimeError(
            "No video files were found in your R2 bucket."
        )

    videos.sort()
    return videos[0]


def create_video_post(channel_id, video_url, caption):
    mutation = f"""
    mutation CreateVideoPost {{
      createPost(
        input: {{
          text: {gql_string(caption)}
          channelId: {gql_string(channel_id)}
          schedulingType: automatic
          mode: addToQueue
          assets: [
            {{
              video: {{
                url: {gql_string(video_url)}
                metadata: {{
                  thumbnailOffset: 2000
                }}
              }}
            }}
          ]
        }}
      ) {{
        ... on PostActionSuccess {{
          post {{
            id
            text
          }}
        }}
        ... on MutationError {{
          message
        }}
      }}
    }}
    """

    result = gql(mutation)

    payload = result["data"]["createPost"]

    if payload.get("message"):
        raise RuntimeError(
            f"Buffer could not create post: {payload['message']}"
        )

    post = payload.get("post")

    if not post:
        raise RuntimeError(
            "Buffer did not return a created post: "
            + json.dumps(payload)
        )

    print(
        f"SUCCESS: Posted/scheduled for channel {channel_id}. "
        f"Post ID: {post['id']}"
    )


def main():
    require(
        "R2_BUCKET_NAME",
        "R2_PREFIX",
        "R2_PUBLIC_URL",
        "BUFFER_API_KEY",
        "INSTAGRAM_CHANNEL_ID",
        "TIKTOK_CHANNEL_ID",
    )

    key = find_next_video()

    print(f"Selected R2 video: {key}")

    video_url = public_url_for_key(key)

    print(f"Public video URL: {video_url}")

    check_public_media(video_url)

    caption = env(
        "POST_CAPTION",
        "New video! 🚀",
    )

    print("Creating Instagram post...")
    create_video_post(
        env("INSTAGRAM_CHANNEL_ID"),
        video_url,
        caption,
    )

    print("Creating TikTok post...")
    create_video_post(
        env("TIKTOK_CHANNEL_ID"),
        video_url,
        caption,
    )

    print("Automation finished successfully.")


if __name__ == "__main__":
    main()
