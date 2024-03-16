from httpx import Response

from .accounts_pool import AccountsPool
from .logger import set_log_level
from .models import Tweet, User, parse_tweet, parse_tweets, parse_user, parse_users
from .queue_client import QueueClient
from .utils import encode_params, find_obj, get_by_path

OP_SearchTimeline = "fZK7JipRHWtiZsTodhsTfQ/SearchTimeline"
OP_UserByRestId = "tD8zKvQzwY3kdx5yz6YmOw/UserByRestId"
OP_UserByScreenName = "k5XapwcSikNsEsILW5FvgA/UserByScreenName"
OP_TweetDetail = "B9_KmbkLhXt6jRwGjJrweg/TweetDetail"
OP_Followers = "ZG1BQPaRSg04qo55kKaW2g/Followers"
OP_Following = "PAnE9toEjRfE-4tozRcsfw/Following"
OP_Retweeters = "X-XEqG5qHQSAwmvy00xfyQ/Retweeters"
OP_Favoriters = "LLkw5EcVutJL6y-2gkz22A/Favoriters"
OP_UserTweets = "5ICa5d9-AitXZrIA3H-4MQ/UserTweets"
OP_UserTweetsAndReplies = "UtLStR_BnYUGD7Q453UXQg/UserTweetsAndReplies"
OP_ListLatestTweetsTimeline = "HjsWc-nwwHKYwHenbHm-tw/ListLatestTweetsTimeline"
OP_Likes = "9s8V6sUI8fZLDiN-REkAxA/Likes"
OP_BlueVerifiedFollowers = "mg4dFO4kMIKt6tpqPMmFeg/BlueVerifiedFollowers"
OP_UserCreatorSubscriptions = "3IgWXBdSRADe5MkzziJV0A/UserCreatorSubscriptions"
OP_AudioSpaceById = "ARXL11vi9i1d3TrrweT9gw/AudioSpaceById"

GQL_URL = "https://twitter.com/i/api/graphql"
GQL_FEATURES = {  # search values here (view source) https://twitter.com/
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_media_download_video_enabled": False,
    "responsive_web_twitter_article_tweet_consumption_enabled": False,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "rweb_video_timestamps_enabled": True,
}


class API:
    # Note: kv is variables, ft is features from original GQL request
    pool: AccountsPool

    def __init__(
        self, pool: AccountsPool | str | None = None, debug=False, proxy: str | None = None
    ):
        if isinstance(pool, AccountsPool):
            self.pool = pool
        elif isinstance(pool, str):
            self.pool = AccountsPool(pool)
        else:
            self.pool = AccountsPool()

        self.proxy = proxy
        self.debug = debug
        if self.debug:
            set_log_level("DEBUG")

    # general helpers

    def _is_end(self, rep: Response, q: str, res: list, cur: str | None, cnt: int, lim: int):
        new_count = len(res)
        new_total = cnt + new_count

        is_res = new_count > 0
        is_cur = cur is not None
        is_lim = lim > 0 and new_total >= lim

        return rep if is_res else None, new_total, is_cur and not is_lim

    def _get_cursor(self, obj: dict, cursor_type="Bottom"):
        if cur := find_obj(obj, lambda x: x.get("cursorType") == cursor_type):
            return cur.get("value")
        return None

    # gql helpers

    async def _gql_items(
        self, op: str, kv: dict, ft: dict | None = None, limit=-1, cursor_type="Bottom"
    ):
        queue, cur, cnt, active = op.split("/")[-1], None, 0, True
        kv, ft = {**kv}, {**GQL_FEATURES, **(ft or {})}

        async with QueueClient(self.pool, queue, self.debug, proxy=self.proxy) as client:
            while active:
                params = {"variables": kv, "features": ft}
                if cur is not None:
                    params["variables"]["cursor"] = cur
                if queue in ("SearchTimeline", "ListLatestTweetsTimeline"):
                    params["fieldToggles"] = {"withArticleRichContentState": False}

                rep = await client.get(f"{GQL_URL}/{op}", params=encode_params(params))
                if rep is None:
                    return

                obj = rep.json()
                els = get_by_path(obj, "entries") or []
                els = [x for x in els if not x["entryId"].startswith("cursor-")]
                cur = self._get_cursor(obj, cursor_type)

                rep, cnt, active = self._is_end(rep, queue, els, cur, cnt, limit)
                if rep is None:
                    return

                yield rep, self._get_cursor(obj, "Top"), self._get_cursor(obj, "Bottom")

    async def _gql_item(self, op: str, kv: dict, ft: dict | None = None):
        ft = ft or {}
        queue = op.split("/")[-1]
        async with QueueClient(self.pool, queue, self.debug, proxy=self.proxy) as client:
            params = {"variables": {**kv}, "features": {**GQL_FEATURES, **ft}}
            return await client.get(f"{GQL_URL}/{op}", params=encode_params(params))

    # search

    async def search_raw(self, q: str, limit=-1, kv=None, cursor_type="Bottom"):
        op = OP_SearchTimeline
        kv = {
            "rawQuery": q,
            "count": 20,
            "product": "Latest",
            "querySource": "typed_query",
            **(kv or {}),
        }
        async for rep, top_cur, bot_cur in self._gql_items(
            op, kv, limit=limit, cursor_type=cursor_type
        ):
            yield rep, top_cur, bot_cur

    async def search(self, q: str, limit=-1, kv=None, cursor_type="Bottom"):
        async for rep, top_cur, bot_cur in self.search_raw(
            q, limit=limit, kv=kv, cursor_type=cursor_type
        ):
            for rep in parse_tweets(rep.json(), limit):
                yield rep, top_cur, bot_cur

    # user_by_id

    async def user_by_id_raw(self, uid: int, kv=None):
        op = OP_UserByRestId
        kv = {"userId": str(uid), "withSafetyModeUserFields": True, **(kv or {})}
        ft = {
            "hidden_profile_likes_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "hidden_profile_subscriptions_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": False,
        }
        return await self._gql_item(op, kv, ft)

    async def user_by_id(self, uid: int, kv=None) -> User | None:
        rep = await self.user_by_id_raw(uid, kv=kv)
        return parse_user(rep) if rep else None

    # user_by_login

    async def user_by_login_raw(self, login: str, kv=None):
        op = OP_UserByScreenName
        kv = {"screen_name": login, "withSafetyModeUserFields": True, **(kv or {})}
        ft = {
            "highlights_tweets_tab_ui_enabled": True,
            "hidden_profile_likes_enabled": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "hidden_profile_subscriptions_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "subscriptions_verification_info_is_identity_verified_enabled": False,
            "responsive_web_twitter_article_notes_tab_enabled": False,
        }
        return await self._gql_item(op, kv, ft)

    async def user_by_login(self, login: str, kv=None) -> User | None:
        rep = await self.user_by_login_raw(login, kv=kv)
        return parse_user(rep) if rep else None

    # tweet_details

    async def tweet_details_raw(self, twid: int, kv=None):
        op = OP_TweetDetail
        kv = {
            "focalTweetId": str(twid),
            "with_rux_injections": True,
            "includePromotedContent": True,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        return await self._gql_item(op, kv)

    async def tweet_details(self, twid: int, kv=None) -> Tweet | None:
        rep = await self.tweet_details_raw(twid, kv=kv)
        return parse_tweet(rep, twid) if rep else None

    async def tweet_details_list(self, twid: int, kv=None) -> Tweet | None:  # type: ignore
        rep = await self.tweet_details_raw(twid, kv=kv)
        for rep in parse_tweets(rep.json()):  # type: ignore
            yield rep  # type: ignore

    # tweet_replies
    # note: uses same op as tweet_details, see: https://github.com/vladkens/twscrape/issues/104

    async def tweet_replies_raw(self, twid: int, limit=-1, kv=None):
        op = OP_TweetDetail
        kv = {
            "focalTweetId": str(twid),
            "referrer": "tweet",
            "with_rux_injections": True,
            "includePromotedContent": True,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        async for x in self._gql_items(op, kv, limit=limit, cursor_type="ShowMoreThreads"):
            yield x

    async def tweet_replies(self, twid: int, limit=-1, kv=None):
        async for rep, _, _ in self.tweet_replies_raw(twid, limit=limit, kv=kv):
            for x in parse_tweets(rep.json(), limit):
                if x.inReplyToTweetId == twid:
                    yield x

    # followers

    async def followers_raw(self, uid: int, limit=-1, kv=None, cursor_type="Bottom"):
        op = OP_Followers
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False, **(kv or {})}
        ft = {"responsive_web_twitter_article_notes_tab_enabled": False}
        async for rep, top_cur, bot_cur in self._gql_items(
            op, kv, limit=limit, cursor_type=cursor_type, ft=ft
        ):
            yield rep, top_cur, bot_cur

    async def followers(self, uid: int, limit=-1, kv=None, cursor_type="Bottom"):
        async for rep, top_cur, bot_cur in self.followers_raw(
            uid, limit=limit, kv=kv, cursor_type=cursor_type
        ):
            for rep in parse_users(rep.json(), limit):
                yield rep, top_cur, bot_cur

    # verified_followers

    async def verified_followers_raw(self, uid: int, limit=-1, kv=None):
        op = OP_BlueVerifiedFollowers
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False, **(kv or {})}
        ft = {"responsive_web_twitter_article_notes_tab_enabled": True}
        async for x in self._gql_items(op, kv, limit=limit, ft=ft):
            yield x

    async def verified_followers(self, uid: int, limit=-1, kv=None):
        async for rep, _, _ in self.verified_followers_raw(uid, limit=limit, kv=kv):
            for x in parse_users(rep.json(), limit):
                yield x

    # following

    async def following_raw(self, uid: int, limit=-1, kv=None, cursor_type="Bottom"):
        op = OP_Following
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False, **(kv or {})}
        async for x, top_cur, bot_cur in self._gql_items(
            op, kv, limit=limit, cursor_type=cursor_type
        ):
            yield x, top_cur, bot_cur

    async def following(self, uid: int, limit=-1, kv=None, cursor_type="Bottom"):
        async for rep, top_cur, bot_cur in self.following_raw(
            uid, limit=limit, kv=kv, cursor_type=cursor_type
        ):
            for x in parse_users(rep.json(), limit):
                yield x, top_cur, bot_cur

    # subscriptions

    async def subscriptions_raw(self, uid: int, limit=-1, kv=None):
        op = OP_UserCreatorSubscriptions
        kv = {"userId": str(uid), "count": 20, "includePromotedContent": False, **(kv or {})}
        async for x in self._gql_items(op, kv, limit=limit):
            yield x

    async def subscriptions(self, uid: int, limit=-1, kv=None):
        async for rep, _, _ in self.subscriptions_raw(uid, limit=limit, kv=kv):
            for x in parse_users(rep.json(), limit):
                yield x

    # retweeters

    async def retweeters_raw(self, twid: int, limit=-1, kv=None, cursor_type="Bottom"):
        op = OP_Retweeters
        kv = {"tweetId": str(twid), "count": 20, "includePromotedContent": True, **(kv or {})}
        async for x, top_cur, bot_cur in self._gql_items(
            op, kv, limit=limit, cursor_type=cursor_type
        ):
            yield x, top_cur, bot_cur

    async def retweeters(self, twid: int, limit=-1, kv=None, cursor_type="Bottom"):
        async for rep, top_cur, bot_cur in self.retweeters_raw(
            twid, limit=limit, kv=kv, cursor_type=cursor_type
        ):
            for x in parse_users(rep.json(), limit):
                yield x, top_cur, bot_cur

    # favoriters

    async def favoriters_raw(self, twid: int, limit=-1, kv=None, cursor_type="Bottom"):
        op = OP_Favoriters
        kv = {"tweetId": str(twid), "count": 20, "includePromotedContent": True, **(kv or {})}
        async for x, top_cur, bot_cur in self._gql_items(
            op, kv, limit=limit, cursor_type=cursor_type
        ):
            yield x, top_cur, bot_cur

    async def favoriters(self, twid: int, limit=-1, kv=None, cursor_type="Bottom"):
        async for rep, top_cur, bot_cur in self.favoriters_raw(
            twid, limit=limit, kv=kv, cursor_type=cursor_type
        ):
            for x in parse_users(rep.json(), limit):
                yield x, top_cur, bot_cur

    # user_tweets

    async def user_tweets_raw(self, uid: int, limit=-1, kv=None, cursor_type="Bottom"):
        op = OP_UserTweets
        kv = {
            "userId": str(uid),
            "count": 40,
            "includePromotedContent": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        async for x, top_cur, bot_cur in self._gql_items(
            op, kv, limit=limit, cursor_type=cursor_type
        ):
            yield x, top_cur, bot_cur

    async def user_tweets(self, uid: int, limit=-1, kv=None, cursor_type="Bottom"):
        async for rep, top_cur, bot_cur in self.user_tweets_raw(
            uid, limit=limit, kv=kv, cursor_type=cursor_type
        ):
            for x in parse_tweets(rep.json(), limit):
                yield x, top_cur, bot_cur

    # user_tweets_and_replies

    async def user_tweets_and_replies_raw(self, uid: int, limit=-1, kv=None, cursor_type="Bottom"):
        op = OP_UserTweetsAndReplies
        kv = {
            "userId": str(uid),
            "count": 40,
            "includePromotedContent": True,
            "withCommunity": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        async for x, top_cur, bot_cur in self._gql_items(
            op, kv, limit=limit, cursor_type=cursor_type
        ):
            yield x, top_cur, bot_cur

    async def user_tweets_and_replies(self, uid: int, limit=-1, kv=None, cursor_type="Bottom"):
        async for rep, top_cur, bot_cur in self.user_tweets_and_replies_raw(
            uid, limit=limit, kv=kv, cursor_type=cursor_type
        ):
            for x in parse_tweets(rep.json(), limit):
                yield x, top_cur, bot_cur

    # list timeline

    async def list_timeline_raw(self, list_id: int, limit=-1, kv=None, cursor_type="Bottom"):
        op = OP_ListLatestTweetsTimeline
        kv = {"listId": str(list_id), "count": 20, **(kv or {})}
        async for x in self._gql_items(op, kv, limit=limit, cursor_type=cursor_type):
            yield x

    async def list_timeline(self, list_id: int, limit=-1, kv=None, cursor_type="Bottom"):
        async for x, top_cur, bot_cur in self.list_timeline_raw(
            list_id, limit=limit, kv=kv, cursor_type=cursor_type
        ):
            for x in parse_tweets(x, limit):
                yield x, top_cur, bot_cur

    # likes

    async def liked_tweets_raw(self, uid: int, limit=-1, kv=None, cursor_type="Bottom"):
        op = OP_Likes
        kv = {
            "userId": str(uid),
            "count": 40,
            "includePromotedContent": True,
            "withVoice": True,
            "withV2Timeline": True,
            **(kv or {}),
        }
        async for x, top_cur, bot_cur in self._gql_items(
            op, kv, limit=limit, cursor_type=cursor_type
        ):
            yield x, top_cur, bot_cur

    async def liked_tweets(self, uid: int, limit=-1, kv=None):
        async for rep, _, _ in self.liked_tweets_raw(uid, limit=limit, kv=kv):
            for x in parse_tweets(rep.json(), limit):
                yield x

    async def audio_space_by_id_raw(self, id: int, kv=None):
        op = OP_AudioSpaceById
        kv = {
            "id": str(id),
            "isMetatagsQuery": True,
            "withReplays": True,
            **(kv or {})
        }
        ft = {
            "spaces_2022_h2_spaces_communities":True,
            "spaces_2022_h2_clipping":True, 
        }
        return await self._gql_item(op, kv, ft)