"""Voiceover script for the 'Aussie animals ranked by how dead you'd be' reel.

Brainrot format: tier board on top, endless-runner gameplay on the bottom, big captions
on the seam. Animals are revealed from F tier up to S, ending on the deadliest.
Each animal flies into its tier row on the letter spoken right before the last "tier"
in its line. "Ay" is spelled that way so the voice says the letter, not "uh";
captions show it as "A".
"""

VOICE = "en-AU-WilliamNeural"
RATE = "+20%"

TIERS = ["S", "A", "B", "C", "D", "F"]

SCENES = [
    {
        "id": "hook",
        "line": "Australian animals, ranked by how dead you'd be. "
                "The last one can kill you in under five minutes.",
    },
    {
        "id": "koala", "tier": "F", "emoji": "🐨", "name": "KOALA", "dead": 0.02,
        "line": "Koala. Sleeps twenty hours a day. Worst case, it scratches you. F tier.",
    },
    {
        "id": "huntsman", "tier": "F", "emoji": "🕷", "tint": (120, 80, 50), "name": "HUNTSMAN SPIDER",
        "dead": 0.04,
        "line": "Huntsman spider. Size of your hand, totally harmless. "
                "You might still die of fright though. F tier.",
    },
    {
        "id": "magpie", "tier": "D", "emoji": "🐦", "tint": (115, 115, 130), "name": "MAGPIE", "dead": 0.07,
        "line": "Magpie. Every spring it dive bombs your head. "
                "Your eyes are at risk. Your life isn't. D tier.",
    },
    {
        "id": "platypus", "tier": "D", "emoji": "🦫", "name": "PLATYPUS", "dead": 0.1,
        "note": "(there is no platypus emoji 💀)",
        "line": "Platypus. It has a venom spike on its back legs. "
                "The pain lasts for weeks, but you'll live. D tier.",
    },
    {
        "id": "kangaroo", "tier": "C", "emoji": "🦘", "name": "KANGAROO", "dead": 0.2,
        "line": "Kangaroo. Two metres tall, kicks like a truck, never skips leg day. C tier.",
    },
    {
        "id": "cassowary", "tier": "C", "emoji": "🦖", "name": "CASSOWARY", "dead": 0.28,
        "note": "(basically a dinosaur)",
        "line": "Cassowary. Basically a velociraptor with a ten centimetre dagger claw. C tier.",
    },
    {
        "id": "taipan", "tier": "B", "emoji": "🐍", "tint": (190, 150, 70), "name": "INLAND TAIPAN",
        "dead": 0.42,
        "line": "Inland taipan. The most venomous snake on Earth. "
                "But it's shy, and lives in the middle of nowhere. B tier.",
    },
    {
        "id": "funnelweb", "tier": "B", "emoji": "🕷", "tint": (90, 72, 110), "name": "FUNNEL-WEB SPIDER",
        "dead": 0.5,
        "line": "Sydney funnel web. Its venom can kill in hours. "
                "But nobody has died since the antivenom came out in 1981. B tier.",
    },
    {
        "id": "shark", "tier": "A", "emoji": "🦈", "name": "GREAT WHITE SHARK", "dead": 0.7,
        "line": "Great white shark. Six metres of teeth, and you're in its kitchen. Ay tier.",
    },
    {
        "id": "brown", "tier": "A", "emoji": "🐍", "tint": (125, 80, 45), "name": "EASTERN BROWN SNAKE",
        "dead": 0.76,
        "line": "Eastern brown snake. Kills more Australians than any other snake. Ay tier.",
    },
    {
        "id": "octopus", "tier": "A", "emoji": "🐙", "tint": (225, 190, 90), "rings": True,
        "name": "BLUE-RINGED OCTOPUS", "dead": 0.85,
        "line": "Blue ringed octopus. The bite doesn't even hurt. "
                "Then you can't breathe. There's no antivenom. Ay tier.",
    },
    {
        "id": "croc", "tier": "S", "emoji": "🐊", "name": "SALTWATER CROC", "dead": 0.97,
        "line": "Saltwater crocodile. A tonne of reptile with the strongest bite ever measured. "
                "If it grabs you, it's over. S tier.",
    },
    {
        "id": "jelly", "tier": "S", "emoji": "🪼", "name": "BOX JELLYFISH", "dead": 1.0,
        "appear": "box",  # suspense card until this word
        "line": "And the deadliest of all. The box jellyfish. "
                "Its sting can stop your heart in under five minutes. S tier. "
                "Follow for part two.",
    },
]
