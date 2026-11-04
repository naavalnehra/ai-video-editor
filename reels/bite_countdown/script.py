"""Voiceover script for the 'How long you'd survive after a bite from...' reel.

Countdown format: each animal gets a bomb timer on top while an ambulance races to hospital in
the "gameplay" clip below, and big captions sit on the seam. Timers run from the longest to the
shortest, then a rabid dog twists the order: the scariest clock isn't the fastest.

`timer` is the seconds on the clock, `label` says what it counts to, `reveal` is the cue word that
slams the real number onto the scrambling digits, `stop` freezes it green (treatment), and
`drain_to` is the fraction left when the scene ends, `hold` is silence after the line so a timer
revealed on the last word still gets to run out. Timer figures are untreated, low-end estimates;
the octopus counts to paralysis because its time of death is poorly documented.
`cues` name words in the line that trigger a visual beat; cues listed in `booms` also get a boom
and a screen shake. Numbers are written as digits so the captions show them that way.
"""

VOICE = "en-AU-WilliamNeural"
RATE = "+15%"

SCENES = [
    {
        "id": "hook",
        "cues": ["bitten", "ambulance", "15", "scariest"], "booms": ["bitten", "15"],
        "line": "You've just been bitten, and the ambulance is miles away. Here's how long you've got. "
                "The fastest timer is 15 minutes. But it's not the scariest.",
    },
    {
        "id": "mamba", "name": "BLACK MAMBA", "emoji": "🐍", "tint": (112, 112, 124), "chip": "3H",
        "timer": 3 * 3600, "reveal": "3", "hold": 1.7, "label": "UNTIL DEATH",
        "stat": "HARD TO BREATHE IN 20 MIN", "stat_cue": "20",
        "cues": ["black", "20", "3"], "booms": ["3"],
        "line": "Black mamba. You're struggling to breathe in 20 minutes. "
                "Without antivenom, you could have as little as 3 hours.",
    },
    {
        "id": "cobra", "name": "KING COBRA", "emoji": "🐍", "tint": (190, 150, 60), "chip": "2H",
        "timer": 2 * 3600, "reveal": "2", "hold": 1.7, "label": "UNTIL DEATH",
        "stat": "BIGGER DOSE. FASTER SYMPTOMS.", "stat_cue": "bigger",
        "cues": ["king", "bigger", "2"], "booms": ["2"],
        "line": "King cobra. Bigger dose, faster symptoms. Fatal cobra bites can take just 2 hours.",
    },
    {
        "id": "taipan", "name": "INLAND TAIPAN", "emoji": "🐍", "tint": (176, 120, 58), "chip": "45M",
        "timer": 45 * 60, "reveal": "45", "label": "UNTIL DEATH",
        "stat": "MOST VENOMOUS SNAKE ON EARTH", "stat_cue": "most",
        "cues": ["inland", "most", "45", "luck"], "booms": ["45"],
        "line": "Inland taipan. The most venomous snake on Earth. "
                "It's quoted at as little as 45 minutes. Luckily, it's shy.",
    },
    {
        "id": "octopus", "name": "BLUE-RINGED OCTOPUS", "emoji": "🐙", "tint": (225, 190, 90), "rings": True,
        "chip": "20M", "timer": 20 * 60, "reveal": "20", "stop": "ventilator", "label": "UNTIL PARALYSIS",
        "stat": "NO ANTIVENOM EXISTS", "stat_cue": "antivenom",
        "cues": ["blue", "hurt", "20", "antivenom", "ventilator"], "booms": ["20"],
        "line": "Blue ringed octopus. The bite barely hurts. Paralysis can start in 20 minutes, "
                "and there's no antivenom. Only a ventilator keeps you breathing.",
    },
    {
        "id": "funnel", "name": "SYDNEY FUNNEL-WEB", "emoji": "🕷", "tint": (150, 125, 185), "chip": "15M",
        "timer": 15 * 60, "reveal": "15", "stop": "antivenom", "label": "UNTIL DEATH",
        "stat": "THE FASTEST HERE", "stat_cue": "fastest",
        "cues": ["sydney", "15", "fastest", "antivenom", "zero"], "booms": ["15", "zero"],
        "line": "Sydney funnel web. The male can kill in as little as 15 minutes. The fastest here. "
                "But since the antivenom arrived in 1981, confirmed deaths? Zero.",
    },
    {
        "id": "twist",
        "cues": ["worse", "this"], "booms": ["this"],
        "line": "So what's worse than 15 minutes? This.",
    },
    {
        "id": "dog", "name": "RABID DOG", "emoji": "🐕", "chip": "90D",
        "timer": 90 * 86400, "days": True, "reveal": "3", "drain_to": 34 / 90, "label": "UNTIL SYMPTOMS",
        "stat": "YOU FEEL TOTALLY FINE", "stat_cue": "fine",
        "cues": ["rabid", "fine", "3", "symptoms", "almost"], "booms": ["almost"],
        "line": "A rabid dog. You feel fine for 1 to 3 months. "
                "Then symptoms start, and it's almost always fatal within days.",
    },
    {
        "id": "shots", "name": "RABID DOG", "emoji": "🐕", "chip": "90D",
        "timer": 34 * 86400, "days": True, "stop": "shots", "label": "UNTIL SYMPTOMS",
        "stat": "THE ONLY WAY OUT", "stat_cue": "only",
        "cues": ["only", "shots", "before"], "booms": ["shots"],
        "line": "The only way to stop this clock? Get the shots before symptoms begin.",
    },
    {
        "id": "outro",
        "cues": ["every", "right", "which", "follow"], "booms": ["right"],
        "line": "Every timer here has the same fix. Get treated, right now. "
                "Which clock scares you most? Follow for more.",
    },
]
