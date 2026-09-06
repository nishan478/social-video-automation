import asyncio
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

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

VIDEOS_PER_PAGE = 8


def get_all_videos():
    """
    Get all video files from Cloudflare R2.
    """
    client = r2_client()

    bucket = env("R2_BUCKET_NAME")
    prefix = env("R2_PREFIX")

    videos = []
    continuation_token = None

    while True:
        kwargs = {
            "Bucket": bucket,
            "Prefix": prefix,
        }

        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        response = client.list_objects_v2(**kwargs)

        for item in response.get("Contents", []):
            key = item["Key"]

            if key.lower().endswith(VIDEO_EXTENSIONS):
                videos.append(key)

        if not response.get("IsTruncated"):
            break

        continuation_token = response.get(
            "NextContinuationToken"
        )

    videos.sort()

    return videos


def create_video_post(channel_id, video_url, caption):
    """
    Ask Buffer to publish the video immediately.
    """

    mutation = f"""
    mutation CreateVideoPost {{
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
            f"Buffer could not create post: "
            f"{payload['message']}"
        )

    post = payload.get("post")

    if not post:
        raise RuntimeError(
            "Buffer did not return a post: "
            + str(payload)
        )

    return post["id"]


def publish_video(key, target):
    """
    Publish selected R2 video to Instagram,
    TikTok, or both.
    """

    video_url = public_url_for_key(key)

    check_public_media(video_url)

    caption = env(
        "POST_CAPTION",
        "New video! 🚀",
    )

    results = {}

    if target in ("instagram", "both"):
        post_id = create_video_post(
            env("INSTAGRAM_CHANNEL_ID"),
            video_url,
            caption,
        )

        results["instagram"] = post_id

    if target in ("tiktok", "both"):
        post_id = create_video_post(
            env("TIKTOK_CHANNEL_ID"),
            video_url,
            caption,
        )

        results["tiktok"] = post_id

    return results


def allowed(update: Update):
    """
    Only allow your Telegram account
    to control the posting bot.
    """

    allowed_id = env("TELEGRAM_ALLOWED_USER_ID")

    if not allowed_id:
        return False

    user = update.effective_user

    if not user:
        return False

    return str(user.id) == allowed_id


async def reject_if_not_allowed(
    update: Update,
):
    if allowed(update):
        return False

    if update.callback_query:
        await update.callback_query.answer(
            "You are not authorized.",
            show_alert=True,
        )

    elif update.message:
        await update.message.reply_text(
            "⛔ You are not authorized to use this bot."
        )

    return True


def video_name(key):
    """
    Make long R2 paths easier to read.
    """

    return key.split("/")[-1]


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if await reject_if_not_allowed(update):
        return

    keyboard = [
        [
            InlineKeyboardButton(
                "📂 Show Videos",
                callback_data="videos:0",
            )
        ]
    ]

    await update.message.reply_text(
        "👋 Welcome to your Video Posting Bot!\n\n"
        "Your videos are stored in Cloudflare R2.\n"
        "Choose a video, select where to post it, "
        "and publish immediately.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def videos_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if await reject_if_not_allowed(update):
        return

    await show_video_page(
        update,
        context,
        0,
        edit=False,
    )


async def show_video_page(
    update,
    context,
    page,
    edit=True,
):
    """
    Display videos with pagination.
    """

    query = update.callback_query

    try:
        videos = await asyncio.to_thread(
            get_all_videos
        )

    except Exception as exc:
        message = (
            "❌ Could not read videos from R2.\n\n"
            f"Error: {exc}"
        )

        if query:
            await query.message.reply_text(message)
        else:
            await update.message.reply_text(message)

        return

    if not videos:
        message = (
            "📂 No video files found in your R2 bucket."
        )

        if query:
            await query.message.reply_text(message)
        else:
            await update.message.reply_text(message)

        return

    total_pages = (
        len(videos) + VIDEOS_PER_PAGE - 1
    ) // VIDEOS_PER_PAGE

    page = max(
        0,
        min(page, total_pages - 1),
    )

    start_index = page * VIDEOS_PER_PAGE
    end_index = start_index + VIDEOS_PER_PAGE

    page_videos = videos[
        start_index:end_index
    ]

    context.user_data["videos"] = videos
    context.user_data["page"] = page

    keyboard = []

    for index, key in enumerate(
        page_videos,
        start=start_index,
    ):
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🎬 {video_name(key)}",
                    callback_data=f"select:{index}",
                )
            ]
        )

    navigation = []

    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                "⬅ Previous",
                callback_data=f"videos:{page - 1}",
            )
        )

    if page < total_pages - 1:
        navigation.append(
            InlineKeyboardButton(
                "Next ➡",
                callback_data=f"videos:{page + 1}",
            )
        )

    if navigation:
        keyboard.append(navigation)

    text = (
        f"📂 Select a video\n\n"
        f"Page {page + 1} of {total_pages}\n"
        f"Total videos: {len(videos)}"
    )

    markup = InlineKeyboardMarkup(
        keyboard
    )

    if query and edit:
        await query.message.edit_text(
            text,
            reply_markup=markup,
        )

    elif query:
        await query.message.reply_text(
            text,
            reply_markup=markup,
        )

    else:
        await update.message.reply_text(
            text,
            reply_markup=markup,
        )


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if await reject_if_not_allowed(update):
        return

    query = update.callback_query

    await query.answer()

    data = query.data

    # Show video page
    if data.startswith("videos:"):
        page = int(
            data.split(":")[1]
        )

        await show_video_page(
            update,
            context,
            page,
        )

        return

    # Select video
    if data.startswith("select:"):
        index = int(
            data.split(":")[1]
        )

        videos = context.user_data.get(
            "videos",
            [],
        )

        if index >= len(videos):
            await query.message.reply_text(
                "❌ Video list expired. "
                "Please run /videos again."
            )
            return

        key = videos[index]

        context.user_data["selected_video"] = key

        keyboard = [
            [
                InlineKeyboardButton(
                    "📸 Instagram",
                    callback_data="target:instagram",
                )
            ],
            [
                InlineKeyboardButton(
                    "🎵 TikTok",
                    callback_data="target:tiktok",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔥 Both Instagram + TikTok",
                    callback_data="target:both",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="cancel",
                )
            ],
        ]

        await query.message.edit_text(
            "🎬 Selected video:\n\n"
            f"{video_name(key)}\n\n"
            "Where do you want to post it?",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

        return

    # Select target
    if data.startswith("target:"):
        target = data.split(":")[1]

        key = context.user_data.get(
            "selected_video"
        )

        if not key:
            await query.message.reply_text(
                "❌ No video selected. "
                "Run /videos again."
            )
            return

        context.user_data["selected_target"] = target

        target_name = {
            "instagram": "📸 Instagram",
            "tiktok": "🎵 TikTok",
            "both": (
                "📸 Instagram + 🎵 TikTok"
            ),
        }[target]

        keyboard = [
            [
                InlineKeyboardButton(
                    "🚀 POST NOW",
                    callback_data="confirm_post",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="cancel",
                )
            ],
        ]

        await query.message.edit_text(
            "⚠️ Ready to publish\n\n"
            f"🎬 Video: "
            f"{video_name(key)}\n"
            f"📍 Destination: "
            f"{target_name}\n\n"
            "Press POST NOW to publish immediately.",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

        return

    # Confirm publishing
    if data == "confirm_post":
        key = context.user_data.get(
            "selected_video"
        )

        target = context.user_data.get(
            "selected_target"
        )

        if not key or not target:
            await query.message.reply_text(
                "❌ Selection expired. "
                "Please run /videos again."
            )
            return

        await query.message.edit_text(
            "⏳ Publishing...\n\n"
            f"🎬 {video_name(key)}"
        )

        try:
            results = await asyncio.to_thread(
                publish_video,
                key,
                target,
            )

        except Exception as exc:
            await query.message.edit_text(
                "❌ Publishing failed.\n\n"
                f"Error:\n{exc}"
            )
            return

        result_text = (
            "✅ Successfully sent to Buffer "
            "for immediate publishing!\n\n"
        )

        if "instagram" in results:
            result_text += (
                "📸 Instagram: requested\n"
            )

        if "tiktok" in results:
            result_text += (
                "🎵 TikTok: requested\n"
            )

        result_text += (
            "\nVideo: "
            f"{video_name(key)}"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "📂 Select Another Video",
                    callback_data="videos:0",
                )
            ]
        ]

        await query.message.edit_text(
            result_text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

        return

    # Cancel
    if data == "cancel":
        context.user_data.pop(
            "selected_video",
            None,
        )

        context.user_data.pop(
            "selected_target",
            None,
        )

        await query.message.edit_text(
            "❌ Cancelled."
        )


def main():
    require(
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_ID",
        "R2_BUCKET_NAME",
        "R2_PREFIX",
        "R2_PUBLIC_URL",
        "BUFFER_API_KEY",
        "INSTAGRAM_CHANNEL_ID",
        "TIKTOK_CHANNEL_ID",
    )

    app = (
        Application.builder()
        .token(
            env("TELEGRAM_BOT_TOKEN")
        )
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "videos",
            videos_command,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    print(
        "Telegram bot is running..."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
