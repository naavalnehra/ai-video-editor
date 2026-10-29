"""Voiceover script for the '$1 million to spend one night in the Daintree' reel.

The night is told as a clock: each hazard scene jumps forward in time and stacks
one more reason to say no. `cue` is the word in the line that reveals the hazard
(emoji slam, sting sound, NOPE-O-METER jump) so visuals stay synced to the voice.
"""

VOICE = "en-AU-WilliamNeural"
RATE = "+10%"

SCENES = [
    {
        "id": "hook",
        "cues": {"money": "million", "place": "daintree", "alone": "alone", "last": "last"},
        "line": "One million dollars to spend one night in the Daintree rainforest. Alone. "
                "Sounds easy, right? Let's see how long you last.",
    },
    {
        "id": "rules",
        "cues": {"tent": "tent", "torch": "torch", "phone": "phone", "sunset": "sunset"},
        "line": "The rules. One tent. One torch. No phone. "
                "Walk in at sunset, walk out at sunrise.",
    },
    {
        "id": "h1", "time": "7:00 PM", "sky": 0.0,
        "emoji": "🐊", "name": "SALTWATER CROC", "stats": ["UP TO 6 M LONG", "HUNTS AT NIGHT"],
        "danger": 5, "nope": 0.2, "cue": "crocodiles",
        "line": "Seven PM. You pitch your tent by the river. Big mistake. "
                "The Daintree River is full of saltwater crocodiles, and they hunt at night.",
    },
    {
        "id": "h2", "time": "9:00 PM", "sky": 0.25,
        "emoji": "🌿", "name": "GYMPIE-GYMPIE", "stats": ["STINGING TREE", "PAIN FOR MONTHS"],
        "danger": 3, "nope": 0.38, "cue": "gympie",
        "line": "Nine PM. Nature calls. You reach for a big, soft-looking leaf. "
                "That's a gympie gympie, a stinging tree. The pain can last for months.",
    },
    {
        "id": "h3", "time": "11:30 PM", "sky": 0.45,
        "emoji": "🕷", "name": "HUNTSMAN", "stats": ["SIZE OF YOUR HAND", "IT'S INSIDE"],
        "danger": 1, "nope": 0.55, "cue": "huntsman",
        "note": "*Harmless to humans. Still absolutely not.",
        "line": "Eleven thirty. Your torch hits the tent wall, and eight little eyes stare back. "
                "A huntsman, the size of your hand. And it's inside.",
    },
    {
        "id": "h4", "time": "2:00 AM", "sky": 0.6,
        "emoji": "🐍", "name": "SCRUB PYTHON", "stats": ["AUSTRALIA'S LONGEST", "UP TO 5 M"],
        "danger": 3, "nope": 0.7, "cue": "python",
        "line": "Two AM. Something heavy slides past your tent. A scrub python. "
                "Australia's longest snake, up to five metres. And it hunts at night.",
    },
    {
        "id": "h5", "time": "4:00 AM", "sky": 0.75,
        "emoji": "tick", "name": "PARALYSIS TICK", "stats": ["HIDES BEHIND EARS", "YES, REAL NAME"],
        "danger": 3, "nope": 0.85, "cue": "paralysis",
        "line": "Four AM. You feel an itch behind your ear. A paralysis tick. "
                "Yes. That is genuinely its name.",
    },
    {
        "id": "h6", "time": "6:00 AM", "sky": 1.0,
        "emoji": "🪼", "name": "BOX JELLYFISH", "stats": ["STINGER SEASON", "DEADLY VENOM"],
        "danger": 5, "nope": 1.0, "cue": "jellyfish",
        "line": "Six AM. Sunrise. You made it! You sprint into the ocean to celebrate. "
                "It's box jellyfish season.",
    },
    {
        "id": "end",
        "cues": {"ask": "would", "comment": "comment"},
        "line": "So. One million dollars. One night in the Daintree. Would you do it? "
                "Comment yes or no, and tag the mate who wouldn't make it to midnight.",
    },
]

HAZARDS = [s for s in SCENES if "cue" in s]
