"""Voiceover script for 'The country where people celebrate New Year 13 days later' reel.

Brainrot format: the calendar story plays on top, a bear-on-a-sled "gameplay" clip runs
on the bottom, and big captions sit on the seam. Spoken at the voice's normal speed.
`cues` name words in the line that trigger a visual beat; cues listed in `booms`
also get a vine-boom and a screen shake.
"""

VOICE = "en-US-AndrewNeural"
RATE = "+0%"

SCENES = [
    {
        "id": "hook",
        "cues": ["twice", "january", "thirteen", "old"], "booms": ["old"],
        "line": "This country celebrates New Year twice. Once on January first, "
                "then again thirteen days later. And yes, they call it the Old New Year.",
    },
    {
        "id": "bug",
        "cues": ["calendar", "russia", "julian", "eleven"], "booms": ["eleven"],
        "line": "Blame a calendar bug. Russia used the Julian calendar, "
                "where every year runs eleven minutes too long.",
    },
    {
        "id": "drift",
        "cues": ["stacks", "thirteen"], "booms": ["thirteen"],
        "line": "That stacks up. By 1918, Russia was thirteen days behind most of Europe.",
    },
    {
        "id": "skip",
        "cues": ["deleted", "people", "bed", "woke", "february"], "booms": ["february"],
        "line": "So Lenin's government deleted thirteen days. People went to bed on "
                "January thirty first, and woke up on February fourteenth.",
    },
    {
        "id": "church",
        "cues": ["church", "old", "christmas"], "booms": ["christmas"],
        "line": "But the Orthodox Church kept the old calendar. "
                "That's why Russian Christmas is on January seventh.",
    },
    {
        "id": "loop",
        "cues": ["new", "christmas", "again"], "booms": ["again"],
        "line": "So the holidays go New Year, Christmas, then New Year again.",
    },
    {
        "id": "food",
        "cues": ["day", "tree", "dumplings", "surprises"], "booms": ["day"],
        "line": "The second one isn't even a day off. People just keep the tree up, "
                "and eat dumplings with surprises hidden inside.",
    },
    {
        "id": "outro",
        "cues": ["in2101", "gap", "fifteenth", "follow"], "booms": ["fifteenth"],
        "line": "And in 2101, the gap grows, and Old New Year moves to January fifteenth. "
                "Follow for more.",
    },
]
