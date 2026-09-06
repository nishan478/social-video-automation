import json

from scripts.common import (
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


def get_video_key():
    """
    Use VIDEO_KEY supplied by GitHub Actions.

    If VIDEO_KEY is empty, find the first video
    available in the configured R2 bucket/prefix.
    """

    video_key = env("VIDEO_KEY", "").strip()

    if video_key:
        print(f"Using requested video: {video_key}")
        return video_key

    print("VIDEO_KEY not provided. Finding a video automatically...")

    client = r2_client()
    bucket = env("R2_BUCKET_NAME")
    prefix = env("R2_PREFIX", "")

    response = client.list_objects_v2(
        Bucket=bucket,
        Prefix=prefix,
    )

    videos = []

    for item in response.get("Contents", []):
        key = item["Key"]

        if key.lower().endswith(VIDEO_EXTENSIONS):
            videos.append(key)

    if not videos:
        raise RuntimeError(
            f"No video files found in R2 bucket '{bucket}' "
            f"with prefix '{prefix}'"
        )

    videos.sort()

    selected_video = videos[0]

    print(f"Automatically selected video: {selected_video}")

    return selected_video


def create_instagram_reel(channel_id, video_url, caption):
    mutation = f"""
    mutation CreateInstagramReel {{
      createPost(
        input: {{
          text: {gql_string(caption)}
          channelId: {gql_string(channel_id)}
          schedulingType: automatic
          mode: shareNow

          metadata: {{
            instagram: {{
              type: reel
              shouldShareToFeed: true
            }}
          }}

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
            f"Buffer could not create Instagram Reel: "
            f"{payload['message']}"
        )

    post = payload.get("post")

    if not post:
        raise RuntimeError(
            "Buffer did not return an Instagram post: "
            + json.dumps(payload)
        )

    print(
        f"SUCCESS: Instagram Reel submitted. "
        f"Post ID: {post['id']}"
    )


def create_tiktok_post(channel_id, video_url, caption):
    mutation = f"""
    mutation CreateTikTokPost {{
      createPost(
        input: {{
          text: {gql_string(caption)}
          channelId: {gql_string(channel_id)}
          schedulingType: automatic
          mode: shareNow

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
            f"Buffer could not create TikTok post: "
            f"{payload['message']}"
        )

    post = payload.get("post")

    if not post:
        raise RuntimeError(
            "Buffer did not return a TikTok post: "
            + json.dumps(payload)
        )

    print(
        f"SUCCESS: TikTok video submitted. "
        f"Post ID: {post['id']}"
    )


def main():
    require(
        "R2_BUCKET_NAME",
        "R2_PUBLIC_URL",
        "BUFFER_API_KEY",
        "INSTAGRAM_CHANNEL_ID",
        "TIKTOK_CHANNEL_ID",
    )

    # Get VIDEO_KEY from GitHub Actions,
    # or automatically select a video from R2.
    key = get_video_key()

    print(f"Selected R2 video: {key}")

    video_url = public_url_for_key(key)

    print(f"Public video URL: {video_url}")

    # Verify that Buffer can access the video publicly.
    check_public_media(video_url)

    caption = env(
        "POST_CAPTION",
        "New video! 🚀",
    )

    print("Posting Instagram Reel...")

    create_instagram_reel(
        env("INSTAGRAM_CHANNEL_ID"),
        video_url,
        caption,
    )

    print("Posting TikTok video...")

    create_tiktok_post(
        env("TIKTOK_CHANNEL_ID"),
        video_url,
        caption,
    )

    print("Automation finished successfully.")


if __name__ == "__main__":
    main()
