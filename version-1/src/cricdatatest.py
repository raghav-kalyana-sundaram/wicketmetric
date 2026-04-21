from cricdata import CricinfoClient

ci = CricinfoClient()

series_slug = "pakistan-in-bangladesh-2025-26-1525632"
match_slug = "bangladesh-vs-pakistan-3rd-odi-1525654"

balls = ci.match_ball_by_ball(series_slug, match_slug)

for innings in balls:
    for ball in innings:
        print(
            ball["shortText"],
            ball["over"]["overs"],
            ball["scoreValue"],
        )


for match in ci.live_matches():
    series = match["series"]
    print(match["title"], "-", series.get("longName", ""))
