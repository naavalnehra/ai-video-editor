"""Voiceover script for the 'Why does Bolivia have a navy?' reel.

Brainrot format: the story plays on top (a map, a court case, a calendar...), a
river-boat "gameplay" clip runs on the bottom, and big captions sit on the seam.
`cues` name words in the line that trigger a visual beat; cues listed in `booms`
also get a vine-boom and a screen shake.
"""

VOICE = "en-US-AndrewNeural"
RATE = "+18%"

SCENES = [
    {
        "id": "hook",
        "cues": ["navy", "ocean", "sailing"], "booms": ["ocean"],
        "line": "Bolivia has a navy. Bolivia has no ocean. So what is it even sailing on?",
    },
    {
        "id": "war",
        "cues": ["fought", "pacific", "lost"], "booms": ["lost"],
        "line": "Plot twist, it used to have a coast. In 1879, Bolivia fought Chile "
                "in the War of the Pacific, and lost the entire coastline.",
    },
    {
        "id": "cope",
        "cues": ["never", "constitution"], "booms": ["constitution"],
        "line": "But Bolivia never moved on. Getting the sea back is literally written "
                "into its constitution.",
    },
    {
        "id": "court",
        "cues": ["world", "lost", "again"], "booms": ["lost", "again"],
        "line": "In 2018, the world court finally ruled on it. Bolivia lost. Again.",
    },
    {
        "id": "seaday",
        "cues": ["march", "day", "doesnt"], "booms": ["doesnt"],
        "line": "Every March twenty third, it celebrates the Day of the Sea. "
                "For a sea it doesn't have.",
    },
    {
        "id": "navy",
        "cues": ["five", "titicaca", "amazon", "smugglers"], "booms": [],
        "line": "So the navy? About five thousand sailors, patrolling Lake Titicaca "
                "and the Amazon rivers, chasing smugglers.",
    },
    {
        "id": "clouds",
        "cues": ["four", "clouds"], "booms": ["clouds"],
        "line": "Titicaca is almost four kilometres above sea level. A navy, in the clouds.",
    },
    {
        "id": "ready",
        "cues": ["promise", "ready"], "booms": ["ready"],
        "line": "And it's a promise. If the coast ever comes back, the navy is ready.",
    },
    {
        "id": "outro",
        "cues": ["paraguay", "navy", "follow"], "booms": ["navy"],
        "line": "Fun fact, Paraguay is landlocked too, and it also has a navy. Follow for more.",
    },
]
