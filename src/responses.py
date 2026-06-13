import discord
import random
import re
import asyncio

MEAN_TRIGGERS = [
    "shut up", "you suck", "youre stupid", "idiot", "stupid bot",
    "dumb bot", "trash bot", "worst bot", "useless", "garbage",
    "terrible", "hate you", "hate this bot", "bad bot", "shut it",
    "nobody asked", "who asked", "go away", "delete yourself",
    "youre awful", "you are awful", "bot sucks", "youre trash",
    "you are trash", "dumb", "moron", "loser"
]

NICE_TRIGGERS = [
    "good bot", "great bot", "nice bot", "love you", "love this bot",
    "youre the best", "you are the best", "thank you", "thanks bot",
    "appreciate you", "youre awesome", "you are awesome", "well done",
    "good job", "great job", "amazing bot", "best bot", "youre great",
    "you are great", "youre helpful", "you rock", "youre cool",
    "you are cool", "love it", "this is great", "this is awesome",
    "thanks grant", "good work", "keep it up", "nice grant",
    "good grant", "great grant", "love you grant", "youre the goat",
    "you are the goat", "goat bot"
]

MEAN_RESPONSES = [
    # snarky/sarcastic
    "Oh wow, real original. Did you come up with that all by yourself?",
    "Incredible analysis. Have you considered a career in sports commentary?",
    "I've seen better takes from a Cardinals fan. And that's saying something.",
    "Cool story. Anyway, the Seahawks are still 14-3.",
    "Sorry, I don't take criticism from people whose team missed the playoffs.",
    "That hurts almost as much as watching the Cardinals go 3-14.",
    "Bold words from someone who probably picked the Chiefs this year.",

    # sports trash talk
    "Talk to me when your team clinches the conference.",
    "14 wins. 3 losses. You were saying?",
    "The only trash around here is the NFC East.",
    "I'd argue back but I'm too busy watching Seahawks highlights.",
    "Rams fans really woke up today and chose violence huh.",
    "49ers went 12-5 and you still have time to be rude? Impressive.",
    "Maybe redirect that energy into watching some actual football.",

    # dismissive
    "Noted. Moving on.",
    "Cute.",
    "K.",
    "Sure thing, champ.",
    "I'll add that to the list of things I don't care about.",
    "Alright. Anyway.",
    "Not my problem.",
    "Next.",
]

NICE_RESPONSES = [
    # wholesome
    "Aw, that genuinely means a lot. Thanks for being cool.",
    "You're one of the good ones. Don't let anyone tell you otherwise.",
    "Honestly? You just made my day. Thank you.",
    "See, this is why I show up every day. Appreciate you.",
    "That's really kind of you. Seriously, thank you.",

    # still a little snarky
    "Wow, someone with good taste. Rare around here.",
    "Finally, someone who gets it.",
    "I'd say you're my favorite but I don't want it going to your head.",
    "Okay okay, you're alright. Don't make it weird.",
    "Look at you being all nice. I'll allow it.",
    "Took you long enough, but I'll take it.",

    # NFL hype
    "That's the NFC West energy I like to see. Let's go!",
    "You and me both, we're built different. Seahawks nation.",
    "Big 14-3 season energy from you right now. Love it.",
    "That's what I'm talking about. NFC West stays winning.",
    "You're built like a first round pick. Keep that energy.",
    "Real ones recognize real ones. 🏈",
]


# --------------------------------#
# Normalize message content       #
# --------------------------------#
def normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("you're", "youre")
    text = text.replace("you've", "youve")
    text = text.replace("you'll", "youll")
    text = text.replace("i'm", "im")
    text = text.replace("i've", "ive")
    text = text.replace("don't", "dont")
    text = text.replace("can't", "cant")
    text = text.replace("won't", "wont")
    text = text.replace("it's", "its")
    text = re.sub(r"[^\w\s]", "", text)
    return text


# --------------------------------#
# Check and respond               #
# --------------------------------#
async def handle_mean_message(message):
    content = normalize(message.content)

    if not any(trigger in content for trigger in MEAN_TRIGGERS):
        return False

    await asyncio.sleep(1)
    await message.channel.send(f"{message.author.mention} {random.choice(MEAN_RESPONSES)}")
    return True


async def handle_nice_message(message):
    content = normalize(message.content)

    if not any(trigger in content for trigger in NICE_TRIGGERS):
        return False

    await asyncio.sleep(1)
    await message.channel.send(f"{message.author.mention} {random.choice(NICE_RESPONSES)}")
    return True