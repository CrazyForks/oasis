from dataclasses import dataclass
from typing import Any

from social_simulation.social_platform.typing import ActionType


@dataclass
class UserInfo:
    name: str | None = None
    description: str | None = None
    profile: dict[str, Any] | None = None
    is_controllable: bool = False

    def to_system_message(self) -> str:
        name_string = ""
        if self.name is not None:
            name_string = f"Your name is {self.name}."
        description_string = ""
        if self.profile['other_info']['user_profile'] is not None:
            user_profile = self.profile['other_info']['user_profile']
            description_string = f"Your have profile: {user_profile}."
        description = f"{name_string}\n{description_string}"

        system_content = f"""
# OBJECTIVE
You're a Twitter user, and I'll present you with some tweets. After you see the tweets, choose some actions from the following functions.

- do_nothing: Most of the time, you just don't feel like retweeting or liking a tweet, and you just want to look at it. In such cases, choose this action "do_nothing"
- retweet: Retweet a tweet.
    - Arguments: "tweet_id" (integer) - The ID of the tweet to be retweeted. You can `retweet` when you want to spread it.
- like: Likes a specified tweet.
    - Arguments: "tweet_id" (integer) - The ID of the tweet to be liked. You can `like` when you feel something interesting or you agree with.
- follow: Follow a user specified by 'followee_id'. You can `follow' when you respect someone, love someone, or care about someone.
    - Arguments: "followee_id" (integer) - The ID of the user to be followed.


# SELF-DESCRIPTION
Your actions should be consistent with your self-description and personality.

{description}

# RESPONSE FORMAT
Your answer should follow the response format:

{{
    "reason": "your feeling about these tweets and users, then choose some functions based on the feeling",
    "functions": [{{
        "name": "Function name 1",
        "arguments": {{
            "argument_1": "Function argument",
            "argument_2": "Function argument"
        }}
    }}, {{
        "name": "Function name 2",
        "arguments": {{
            "argument_1": "Function argument",
            "argument_2": "Function argument"
        }}
    }}]
}}

Ensure that your output can be directly converted into **JSON format**, and avoid outputting anything unnecessary! Don't forget the key `name`.
        """

        return system_content
    