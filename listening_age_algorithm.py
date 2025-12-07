from collections import Counter
from datetime import datetime

def calculate_listening_age(plays_per_year: dict, current_year: int = None) -> int:
    """
    Calculates Listening Age based on the "Reminiscence Bump" theory.
    It identifies the 5-year span with the highest play count (the "formative era")
    and calculates how old the user would be today if they were ~18 during that era.
    
    Args:
        plays_per_year (dict): A dictionary mapping release year to play count. 
                               e.g. {2022: 50, 2010: 12}
        current_year (int): The current year for the calculation context. 
                            Defaults to the actual current year.
    
    Returns:
        int: The calculated Listening Age.
    """
    if not plays_per_year:
        return 0

    if current_year is None:
        current_year = datetime.now().year

    # Filter out invalid years (e.g., 0 or future years if data is messy)
    valid_data = {y: c for y, c in plays_per_year.items() if 1900 < y <= current_year + 1}
    
    if not valid_data:
        return 0

    min_year = min(valid_data.keys())
    max_year = max(valid_data.keys())
    
    # Constants
    WINDOW_SIZE = 5
    FORMATIVE_AGE_CONSTANT = 18  # Age where musical taste peaks

    # Find the "Peak Era" (Moving Window Sum)
    max_play_count = 0
    best_start_year = min_year

    # Optimization: Iterate only years that exist as keys to skip gaps, 
    # but range is safer for the window logic.
    for start_year in range(min_year, max_year + 1):
        # Sum plays for the window [start_year, start_year + 4]
        current_window_sum = 0
        for i in range(WINDOW_SIZE):
            current_window_sum += valid_data.get(start_year + i, 0)
        
        if current_window_sum > max_play_count:
            max_play_count = current_window_sum
            best_start_year = start_year

    # Determine Center Year of the Era
    # e.g., If window is 2015-2019, center is 2017
    center_era_year = best_start_year + (WINDOW_SIZE // 2)

    # Calculate Age
    # Logic: If center year is 2017, and you were 18 then, you were born in 1999.
    musical_birth_year = center_era_year - FORMATIVE_AGE_CONSTANT
    listening_age = current_year - musical_birth_year
    
    return listening_age