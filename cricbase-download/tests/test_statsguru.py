from datetime import date

from cricbase.statsguru import parse_batting_rows, parse_date, parse_fow_rows, parse_player_cell, parse_year_matches


def test_parse_date_formats():
    assert parse_date("15 Mar 1877") == date(1877, 3, 15)
    assert parse_date("Jan 5, 1971") == date(1971, 1, 5)
    assert parse_date("Mar 15-19, 1877") == date(1877, 3, 15)
    assert parse_date("Mar 31-Apr 4, 1877") == date(1877, 3, 31)
    assert parse_date("Jun 27-Jul 1, 1930") == date(1930, 6, 27)
    assert parse_date("Dec 31, 1881 - Jan 4, 1882") == date(1881, 12, 31)


YEAR_HTML = """
<table class="engineTable">
<tr><th>Team 1</th><th>Team 2</th><th>Winner</th><th>Margin</th><th>Ground</th><th>Match Date</th><th>Scorecard</th></tr>
<tr class="data1">
<td>Australia</td><td>England</td><td>Australia</td><td>45 runs</td>
<td>Melbourne</td><td>Mar 15-19, 1877</td>
<td><a href="/ci/engine/match/62396.html">Test # 1</a></td>
</tr>
<tr class="data1">
<td>India</td><td>Kenya</td><td>India</td><td>10 wickets</td>
<td>Bengaluru</td><td>Jan 1, 1998</td>
<td><a href="/ci/engine/match/99999.html">ODI # 1</a></td>
</tr>
<tr class="data1">
<td>England</td><td>Australia</td><td>drawn</td>
<td>Leeds</td><td>Jul 11-15, 1930</td>
<td><a href="/ci/engine/match/62648.html">Test # 196</a></td>
</tr>
</table>
"""


def test_year_matches_keep_test_nations_only():
    rows = parse_year_matches(YEAR_HTML, "Test")
    assert [row["match_id"] for row in rows] == ["62396", "62648"]
    assert rows[0]["team1"] == "Australia"
    assert rows[0]["start_date"] == "1877-03-15"
    assert rows[0]["win_runs"] == 45
    assert rows[1]["result"] == "draw"
    assert rows[1]["start_date"] == "1930-07-11"


def test_year_matches_odi_keeps_associates():
    rows = parse_year_matches(YEAR_HTML, "ODI")
    ids = [row["match_id"] for row in rows]
    assert "99999" in ids
    kenya = next(row for row in rows if row["match_id"] == "99999")
    assert kenya["team2"] == "Kenya"
    assert kenya["win_wickets"] == 10


BATTING_HTML = """
<table class="engineTable">
<tr><th>Player</th><th>Runs</th><th>Mins</th><th>BF</th><th>4s</th><th>6s</th><th>SR</th><th>Inns</th><th></th><th>Opposition</th><th>Ground</th><th>Start Date</th></tr>
<tr class="data1">
<td class="left"><a href="/ci/content/player/4091.html">C Bannerman</a> (AUS)</td>
<td>165*</td><td>285</td><td>-</td><td>18</td><td>0</td><td>-</td><td>1</td><td></td>
<td>v <a href="/ci/content/team/1.html">England</a></td>
<td>Melbourne</td><td><b>15 Mar 1877</b></td>
</tr>
</table>
"""


def test_parse_batting_not_out():
    rows = parse_batting_rows(BATTING_HTML)
    assert len(rows) == 1
    assert rows[0]["cricinfo_id"] == "4091"
    assert rows[0]["team"] == "Australia"
    assert rows[0]["runs"] == 165
    assert rows[0]["not_out"] == 1
    assert rows[0]["opposition"] == "England"
    assert rows[0]["start_date"] == "1877-03-15"


def test_parse_player_cell_invitational_sides():
    from bs4 import BeautifulSoup

    html = '<td class="left"><a href="/ci/content/player/8166.html">SK Warne</a> (ICC)</td>'
    cell = BeautifulSoup(html, "lxml").td
    cricinfo_id, name, team = parse_player_cell(cell)
    assert cricinfo_id == "8166"
    assert name == "SK Warne"
    assert team == "ICC World XI"

    html = '<td class="left"><a href="/ci/content/player/1.html">X</a> (KEN)</td>'
    cell = BeautifulSoup(html, "lxml").td
    _, _, team = parse_player_cell(cell)
    assert team == "Kenya"


DNB_HTML = """
<table class="engineTable">
<tr><th>Player</th><th>Runs</th><th>Mins</th><th>BF</th><th>4s</th><th>6s</th><th>SR</th><th>Inns</th><th></th><th>Opposition</th><th>Ground</th><th>Start Date</th></tr>
<tr class="data1">
<td class="left"><a href="/ci/content/player/30176.html">A Kumble</a> (IND)</td>
<td class="padAst">DNB</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>2</td><td></td>
<td>v <a href="/ci/content/team/5.html">New Zealand</a></td>
<td>Auckland</td><td><b>27 Mar 1994</b></td>
</tr>
<tr class="data1">
<td class="left"><a href="/ci/content/player/35320.html">SR Tendulkar</a> (IND)</td>
<td>82</td><td>90</td><td>49</td><td>15</td><td>2</td><td>167.3</td><td>2</td><td></td>
<td>v <a href="/ci/content/team/5.html">New Zealand</a></td>
<td>Auckland</td><td><b>27 Mar 1994</b></td>
</tr>
</table>
"""


def test_parse_batting_skips_dnb():
    rows = parse_batting_rows(DNB_HTML)
    assert len(rows) == 1
    assert rows[0]["name"] == "SR Tendulkar"
    assert rows[0]["runs"] == 82


FOW_HTML = """
<table class="engineTable">
<tr><th>Partners</th><th>Wkt</th><th>Runs</th><th>In</th><th>Out</th><th>Inns</th><th></th><th>Opposition</th><th>Ground</th><th>Start Date</th></tr>
<tr class="data1">
<td class="left"><a href="/ci/content/player/35320.html">SR Tendulkar</a>, <a href="/ci/content/player/29646.html">A Jadeja</a> (IND)</td>
<td>1</td><td>41</td><td>-</td><td>1/41</td><td>2</td><td></td>
<td>v <a href="/ci/content/team/5.html">New Zealand</a></td>
<td>Auckland</td><td><b>27 Mar 1994</b></td>
</tr>
<tr class="data1">
<td class="left"><a href="/ci/content/player/31742.html">M Azharuddin</a>, <a href="/ci/content/player/30958.html">SV Manjrekar</a> (IND)</td>
<td>4</td><td>19*</td><td>3/124</td><td>3/143</td><td>2</td><td></td>
<td>v <a href="/ci/content/team/5.html">New Zealand</a></td>
<td>Auckland</td><td><b>27 Mar 1994</b></td>
</tr>
</table>
"""


def test_parse_fow_partnerships():
    rows = parse_fow_rows(FOW_HTML)
    assert len(rows) == 2
    first = rows[0]
    assert first["name_1"] == "SR Tendulkar"
    assert first["name_2"] == "A Jadeja"
    assert first["cricinfo_id_1"] == "35320"
    assert first["team"] == "India"
    assert first["wicket_number"] == 1
    assert first["runs"] == 41
    assert first["not_out"] == 0
    assert first["innings_number"] == 2
    last = rows[1]
    assert last["runs"] == 19
    assert last["not_out"] == 1
    assert last["opposition"] == "New Zealand"
    assert last["start_date"] == "1994-03-27"

