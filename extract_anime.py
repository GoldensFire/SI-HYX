import json
import sys

with open(r'C:\Users\ConterStirk\AppData\Roaming\unified_media_tool\animepack_shikimori_db.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Get all anime from both buckets
all_anime = {}
for bucket_name, bucket in data['anime'].items():
    if 'cards' in bucket and isinstance(bucket['cards'], dict):
        for aid, card in bucket['cards'].items():
            all_anime[aid] = card

print(f'Total unique anime: {len(all_anime)}', file=sys.stderr)

# Extract IDs and names
anime_list = []
for aid, card in all_anime.items():
    name = card.get('name', '')
    russian = card.get('russian', '')
    kind = card.get('kind', '')
    episodes = card.get('episodes', 0)
    score = card.get('score', 0)
    genres = [g.get('name', '') for g in card.get('genres', []) if isinstance(g, dict)]
    anime_list.append({
        'id': aid,
        'name': name,
        'russian': russian,
        'kind': kind,
        'episodes': episodes,
        'score': score,
        'genres': genres
    })

# Sort by score descending to get popular ones first
anime_list.sort(key=lambda x: x['score'], reverse=True)

# Save to file
with open('anime_list.json', 'w', encoding='utf-8') as f:
    json.dump(anime_list, f, ensure_ascii=False, indent=2)

print('Saved anime_list.json', file=sys.stderr)
print('Top 20 by score:', file=sys.stderr)
for a in anime_list[:20]:
    display_name = a['russian'] or a['name']
    print(f"  {a['id']}: {display_name} (score: {a['score']}, kind: {a['kind']}, eps: {a['episodes']})", file=sys.stderr)