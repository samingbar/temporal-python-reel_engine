from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QueryInfo:
    query: str = "viral dog reels"
    dog_profile: str = (
        "Cute and loyal German Shepherd named Mushroom (Musher, Mushy), 4 y/o, Seattle. "
        "Enjoys homemade treats, indoor ball play, new places, howling at firetrucks, "
        "chasing rabbits & squirrels, and barking at visitors."
    )
    min_ideas: int = 3
    max_ideas: int = 5

    def __post_init__(self):
        if self.min_ideas < 1:
            raise ValueError("min_ideas must be >= 1")
        if self.max_ideas < self.min_ideas:
            raise ValueError("max_ideas must be >= min_ideas")
