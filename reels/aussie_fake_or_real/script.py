"""Voiceover script for the 'Things Americans think are fake about Australia' reel.

Brainrot format: claims and real-or-fake verdicts play on top, an outback ute "gameplay"
clip runs on the bottom, and big captions sit on the seam. Spoken at the voice's normal
speed. `cues` name words in the line that trigger a visual beat; cues listed in `booms`
also get a vine-boom and a screen shake.
"""

VOICE = "en-AU-WilliamNeural"
RATE = "+0%"

SCENES = [
    {
        "id": "hook",
        "cues": ["americans", "drop", "spiders", "birds", "real"], "booms": ["real"],
        "line": "Americans think these three things about Australia are made up. Drop bears. "
                "Spiders the size of a plate. And birds that steal your food. So which ones are real?",
    },
    {
        "id": "bear_claim",
        "cues": ["killer", "fall", "tourists"], "booms": ["fall"],
        "line": "First, drop bears. Killer koalas that fall out of trees onto your head. "
                "Aussies love warning tourists about them.",
    },
    {
        "id": "bear_verdict",
        "cues": ["fake", "prank", "vegemite", "museum", "joke"], "booms": ["fake"],
        "line": "The verdict? Completely fake. It's a prank, and we tell tourists to wear "
                "Vegemite behind their ears to stay safe. The Australian Museum even has a page on them, "
                "as a joke.",
    },
    {
        "id": "spider_claim",
        "cues": ["spiders", "plate", "exaggerating"], "booms": ["exaggerating"],
        "line": "Next, spiders the size of a plate. Surely we're exaggerating.",
    },
    {
        "id": "spider_verdict",
        "cues": ["half", "golden", "fifteen", "side", "dinner", "laos"], "booms": ["half", "laos"],
        "line": "Half real. Our biggest huntsman, the golden huntsman, spans about fifteen centimetres. "
                "That's a side plate. The dinner plate sized one lives in Laos.",
    },
    {
        "id": "bird_claim",
        "cues": ["birds", "seagull"], "booms": [],
        "line": "Last, birds that steal your food. Sounds like a normal seagull problem, right?",
    },
    {
        "id": "bird_verdict",
        "cues": ["real", "kookaburras", "ibis", "chickens", "cockatoos", "taught", "three", "forty"],
        "booms": ["real", "forty"],
        "line": "Nope, it's very real. Kookaburras raid picnics and barbecues. Ibis snatch food "
                "so often we call them bin chickens. And Sydney's cockatoos learned to open wheelie bins, "
                "then taught each other. It spread from three suburbs to forty four.",
    },
    {
        "id": "outro",
        "cues": ["one", "half", "very", "sandwich", "follow"], "booms": ["sandwich"],
        "line": "So that's one fake, one half real, and one very real. "
                "Still don't believe us? Bring a sandwich. Follow for more.",
    },
]
