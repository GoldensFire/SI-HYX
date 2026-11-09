import json
import re

# Load the anime list from Shikimori cache
with open('anime_list.json', 'r', encoding='utf-8') as f:
    anime_list = json.load(f)

# Create a lookup by name (English, Russian, Japanese, synonyms)
anime_by_name = {}
for anime in anime_list:
    names = set()
    if anime['name']:
        names.add(anime['name'].lower())
    if anime['russian']:
        names.add(anime['russian'].lower())
    # Add partial matches for common abbreviations
    for name in list(names):
        # Remove common suffixes
        clean = re.sub(r'\s*[:：\-–—].*$', '', name)
        clean = re.sub(r'\s*\(\d{4}\)\s*$', '', clean)
        clean = re.sub(r'\s*(сезон|season|часть|part|фильм|movie|ova|ona|спешл|special|tv)\b.*$', '', clean, flags=re.IGNORECASE)
        if clean != name:
            names.add(clean.strip())
    for n in names:
        if n:
            anime_by_name[n] = anime

print(f"Total anime in cache: {len(anime_list)}")
print(f"Total name entries in lookup: {len(anime_by_name)}")

# Load the Letterboxd CSV
with open('67-six-seven.csv', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Parse CSV - find anime entries
anime_entries = []
in_data = False
for line in lines:
    line = line.strip()
    if line.startswith('Position,Name,Year,URL,Description'):
        in_data = True
        continue
    if in_data and line:
        # Parse CSV line
        parts = line.split(',', 4)
        if len(parts) >= 3:
            pos = parts[0]
            name = parts[1].strip('"')
            year = parts[2]
            # Check if this might be anime
            name_lower = name.lower()
            # Look for anime keywords
            anime_keywords = ['anime', 'chainsaw man', 'demon slayer', 'kimetsu', 'jujutsu', 'attack on titan', 'shingeki', 
                             'my hero academia', 'boku no hero', 'one piece', 'naruto', 'bleach', 'death note',
                             'fullmetal', 'steins;gate', 're:zero', 'overlord', 'isekai', 'tensei', 'slime',
                             'spy x family', 'bocchi', 'chainsaw', 'jojo', 'gundam', 'evangelion', 'code geass',
                             'fate/', 'monogatari', 'kaguya', 'komi', 'spy family', 'mushoku', 'shield hero',
                             'dragon ball', 'pokemon', 'digimon', 'yugioh', 'sailor moon', 'precure',
                             'haikyuu', 'kuroko', 'free!', 'yuri on ice', 'given', 'banana fish',
                             'vinland saga', 'golden kamuy', 'dorohedoro', 'beastars', 'promare',
                             'weathering with you', 'your name', 'a silent voice', 'maquia',
                             'chainsaw man', 'dandadan', 'frieren', 'sousou no frieren']
            
            is_anime = any(kw in name_lower for kw in anime_keywords)
            # Also check if it's in our cache
            in_cache = name_lower in anime_by_name
            
            if is_anime or in_cache:
                anime_entries.append({
                    'position': pos,
                    'name': name,
                    'year': year,
                    'in_cache': in_cache,
                    'matched_name': name_lower if in_cache else None
                })

print(f"\nFound {len(anime_entries)} potential anime entries in Letterboxd list:")
for entry in anime_entries:
    status = "[IN CACHE]" if entry['in_cache'] else "[not in cache]"
    print(f"  {entry['position']}: {entry['name']} ({entry['year']}) - {status}")

# Now let's also search for partial matches in our cache
print("\n\nSearching for partial matches in cache...")
# Let's look for any anime in cache that might have "six seven" related content
# We'll check titles that might relate to numbers, counting, etc.
number_related = []
for anime in anime_list:
    names = [anime['name'], anime['russian']]
    for name in names:
        if not name:
            continue
        name_lower = name.lower()
        # Check for number-related words
        if any(w in name_lower for w in ['six', 'seven', '6', '7', 'шесть', 'семь', 'count', 'счет', 'number', 'номер']):
            number_related.append(anime)

print(f"\nAnime in cache with number-related titles: {len(number_related)}")
for a in number_related[:30]:
    print(f"  {a['id']}: {a['russian'] or a['name']}")