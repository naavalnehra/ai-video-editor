"""Voiceover script for the 'Your raccoon vs our spider' reel (USA vs Australia).

Each round scene shows the American animal (left) against the Australian one (right).
`cues` are words in the line that trigger each side's entrance and the winner reveal,
so the visuals stay synced to the voiceover.
"""

VOICE = "en-AU-WilliamNeural"
RATE = "+8%"

SCENES = [
    {
        "id": "hook",
        "headline": "YOUR RACCOON\nVS OUR\nSPIDER",
        "line": "Your raccoon versus our spider. "
                "American animals against Australian ones. Five rounds, one winner.",
    },
    {
        "id": "r1",
        "headline": "ROUND 1",
        "usa": {"emoji": "🦝", "name": "RACCOON", "stats": ["OPENS LATCHES", "RAIDS YOUR BINS"],
                "threat": 0.35},
        "aus": {"emoji": "🕷", "name": "HUNTSMAN", "stats": ["SIZE OF YOUR HAND", "LIVES IN YOUR CAR"],
                "threat": 0.8},
        "cues": {"usa": "raccoon", "aus": "huntsman", "reveal": "point"},
        "winner": "aus",
        "line": "Round one. Your raccoon can open bins and door latches. "
                "Our huntsman spider is the size of your hand, and hides in your car's sun visor. "
                "Point, Australia.",
    },
    {
        "id": "r2",
        "headline": "ROUND 2",
        "usa": {"emoji": "🐍", "name": "RATTLESNAKE", "stats": ["WARNS YOU FIRST", "RATTLE INCLUDED"],
                "threat": 0.55},
        "aus": {"emoji": "🐍", "name": "INLAND TAIPAN", "stats": ["MOST TOXIC VENOM", "OF ANY LAND SNAKE"],
                "threat": 0.97},
        "cues": {"usa": "rattlesnake", "aus": "taipan", "reveal": "point"},
        "winner": "aus",
        "note": "*It's actually very shy. Bites are extremely rare.",
        "line": "Round two. Your rattlesnake gives you a polite warning rattle. "
                "Our inland taipan has the most toxic venom of any land snake on Earth. "
                "Point, Australia.",
    },
    {
        "id": "r3",
        "headline": "ROUND 3",
        "usa": {"emoji": "🐻", "name": "GRIZZLY", "stats": ["UP TO 360 KG", "RUNS 55 KM/H"],
                "threat": 0.95},
        "aus": {"emoji": "🦘", "name": "KANGAROO", "stats": ["NEARLY 2 M TALL", "BRUTAL KICK"],
                "threat": 0.5},
        "cues": {"usa": "grizzly", "aus": "kangaroo", "reveal": "point"},
        "winner": "usa",
        "line": "Round three. Our kangaroo kicks hard and stands nearly two metres tall. "
                "But your grizzly bear weighs up to three hundred and sixty kilos. "
                "Point, America.",
    },
    {
        "id": "r4",
        "headline": "ROUND 4",
        "usa": {"emoji": "🫎", "name": "MOOSE", "stats": ["UP TO 700 KG", "BAD TEMPER"],
                "threat": 0.85},
        "aus": {"emoji": "🦖", "name": "CASSOWARY", "stats": ["10 CM DAGGER CLAW", "BASICALLY A DINO"],
                "threat": 0.75},
        "cues": {"usa": "moose", "aus": "cassowary", "reveal": "point"},
        "winner": "usa",
        "line": "Round four. Our cassowary is basically a dinosaur with a ten centimetre dagger claw. "
                "Your moose? Up to seven hundred kilos of bad mood. "
                "Point, America.",
    },
    {
        "id": "r5",
        "headline": "FINAL ROUND",
        "usa": {"emoji": "🐊", "name": "ALLIGATOR", "stats": ["~4.5 M LONG", "~450 KG"],
                "threat": 0.7},
        "aus": {"emoji": "🐊", "name": "SALTWATER CROC", "stats": ["6 M+ LONG", "~1,000 KG"],
                "threat": 0.98},
        "cues": {"usa": "alligator", "aus": "saltwater", "reveal": "point"},
        "winner": "aus",
        "line": "Final round, two all. Your alligator grows to about four and a half metres. "
                "Our saltwater crocodile hits six, the biggest reptile alive. "
                "Point, Australia.",
    },
    {
        "id": "winner",
        "headline": "AUSTRALIA\nWINS",
        "line": "Final score, three to two. Australia wins. "
                "Sorry America, but at least your spiders stay outside. Follow for round two.",
    },
]
