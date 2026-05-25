# Conditional attention findings

Per-pair attention from the frame-VAEP transformer (2 layers x 4 heads, mean over layers + heads), bucketed by frame outcome label:
- **score**: y_score == 1 (team in possession scores within 10 s)
- **concede**: y_concede == 1
- **neutral**: both labels 0

Filters: same-team pairs with minutes_together >= 60.0 and >= 50 bucket-frames in both numerator and denominator.

## Q1 - Mean attention per frame, category x bucket (same-team)

| Category | score | concede | neutral |
|---|---:|---:|---:|
| off | 0.0614 | 0.0600 | 0.0663 |
| def | 0.1200 | 0.1007 | 0.1001 |
| cross | 0.0975 | 0.0872 | 0.0895 |

## Q2 - Top 20 off-off pairs by score-frame lift

These are off-off pairs the model attends to above its own neutral baseline specifically when scoring is imminent.

| # | Team | Pair | Min | score/f | neutral/f | Lift |
|---:|---|---|---:|---:|---:|---:|
| 1 | Morocco | Hakim Ziyech + Abderrazak Hamdallah | 69 | 0.1129 | 0.0560 | **2.02x** |
| 2 | Morocco | Hakim Ziyech + Zakaria Aboukhlal | 64 | 0.1172 | 0.0583 | **2.01x** |
| 3 | United States | Josh Sargent + Yunus Musah | 163 | 0.1320 | 0.0710 | **1.86x** |
| 4 | Japan | Ao Tanaka + Daizen Maeda | 118 | 0.0780 | 0.0421 | **1.85x** |
| 5 | Morocco | Hakim Ziyech + Azzedine Ounahi | 543 | 0.1145 | 0.0657 | **1.74x** |
| 6 | Morocco | Youssef En-Nesyri + Azzedine Ounahi | 481 | 0.0973 | 0.0567 | **1.72x** |
| 7 | Croatia | Ivan Perisic + Marko Livaja | 232 | 0.1252 | 0.0730 | **1.71x** |
| 8 | Netherlands | Davy Klaassen + Teun Koopmeiners | 91 | 0.1040 | 0.0619 | **1.68x** |
| 9 | United States | Timothy Weah + Josh Sargent | 150 | 0.1177 | 0.0729 | **1.61x** |
| 10 | Uruguay | Federico Valverde + Giorgian De Arrascaeta | 118 | 0.0933 | 0.0581 | **1.61x** |
| 11 | Morocco | Azzedine Ounahi + Abdelhamid Sabiri | 84 | 0.0934 | 0.0584 | **1.60x** |
| 12 | Cameroon | Pierre Kunde + Vincent Aboubakar | 80 | 0.0891 | 0.0557 | **1.60x** |
| 13 | Germany | Leroy Sané + Niclas Fullkrug | 73 | 0.1096 | 0.0689 | **1.59x** |
| 14 | Uruguay | Facundo Pellistri + Giorgian De Arrascaeta | 104 | 0.1160 | 0.0736 | **1.58x** |
| 15 | Morocco | Sofiane Boufal + Azzedine Ounahi | 423 | 0.0977 | 0.0637 | **1.53x** |
| 16 | Uruguay | Luis Suarez + Facundo Pellistri | 156 | 0.1114 | 0.0729 | **1.53x** |
| 17 | Australia | Aaron Mooy + Keanu Baccus | 131 | 0.0723 | 0.0487 | **1.48x** |
| 18 | France | Olivier Giroud + Aurélien Tchouaméni | 410 | 0.0862 | 0.0585 | **1.47x** |
| 19 | Uruguay | Federico Valverde + Facundo Pellistri | 191 | 0.0998 | 0.0678 | **1.47x** |
| 20 | Mexico | Raúl Jiménez + Luis Chávez | 79 | 0.0819 | 0.0558 | **1.47x** |

## Q3 - Top 20 def-def pairs by concede-frame lift

Sanity check: defensive pairs SHOULD fire above baseline when conceding is imminent.

| # | Team | Pair | Min | concede/f | neutral/f | Lift |
|---:|---|---|---:|---:|---:|---:|
| 1 | Costa Rica | Kendall Waston + Keylor Navas | 244 | 0.2168 | 0.1019 | **2.13x** |
| 2 | Ghana | Mohammed Salisu + Gideon Mensah | 88 | 0.1063 | 0.0555 | **1.92x** |
| 3 | Portugal | Raphaël Guerreiro + Diogo Costa | 304 | 0.2417 | 0.1286 | **1.88x** |
| 4 | Canada | Kamal Miller + Sam Adekugbe | 106 | 0.1449 | 0.0771 | **1.88x** |
| 5 | Senegal | Ismail Jakobs + Kalidou Koulibaly | 296 | 0.1193 | 0.0641 | **1.86x** |
| 6 | France | Hugo Lloris + Raphael Varane | 460 | 0.2452 | 0.1325 | **1.85x** |
| 7 | France | Hugo Lloris + Jules Kounde | 484 | 0.2569 | 0.1405 | **1.83x** |
| 8 | Australia | Milos Degenek + Harry Souttar | 202 | 0.1294 | 0.0748 | **1.73x** |
| 9 | Canada | Steven Vitoria + Sam Adekugbe | 106 | 0.1428 | 0.0832 | **1.72x** |
| 10 | Switzerland | Gregor Kobel + Silvan Widmer | 100 | 0.2408 | 0.1411 | **1.71x** |
| 11 | Switzerland | Fabian Schär + Gregor Kobel | 100 | 0.2188 | 0.1285 | **1.70x** |
| 12 | Australia | Harry Souttar + Kye Rowles | 387 | 0.0988 | 0.0581 | **1.70x** |
| 13 | Canada | Alistair Johnston + Sam Adekugbe | 106 | 0.1373 | 0.0816 | **1.68x** |
| 14 | France | Hugo Lloris + Ibrahima Konaté | 216 | 0.2222 | 0.1425 | **1.56x** |
| 15 | Spain | Pau Torres + Alex Balde | 68 | 0.0972 | 0.0625 | **1.56x** |
| 16 | Germany | Antonio Rüdiger + Manuel Neuer | 294 | 0.2398 | 0.1570 | **1.53x** |
| 17 | France | Hugo Lloris + Theo Hernandez | 548 | 0.2106 | 0.1384 | **1.52x** |
| 18 | Croatia | Borna Sosa + Dominik Livakovic | 426 | 0.2077 | 0.1371 | **1.51x** |
| 19 | Senegal | Ismail Jakobs + Youssouf Sabaly | 296 | 0.1101 | 0.0728 | **1.51x** |
| 20 | Brazil | Alisson + Eder Militao | 248 | 0.2368 | 0.1568 | **1.51x** |

## Q4 - Top 15 cross-team pairs by score-frame lift

| # | Pair | Teams | Min | Lift |
|---:|---|---|---:|---:|
| 1 | Jordan Pickford + Joe Allen | England / Wales | 80 | **2.40x** |
| 2 | Daniel James + Jordan Pickford | Wales / England | 76 | **2.27x** |
| 3 | Jordan Pickford + Aaron Ramsey | England / Wales | 94 | **2.21x** |
| 4 | Jordan Pickford + Kieffer Moore | England / Wales | 94 | **2.20x** |
| 5 | Timothy Weah + Jurrien Timber | United States / Netherlands | 66 | **2.08x** |
| 6 | Jordan Pickford + Ethan Ampadu | England / Wales | 94 | **2.07x** |
| 7 | Jordan Pickford + Joe Rodon | England / Wales | 94 | **2.06x** |
| 8 | Jordan Pickford + Chris Mepham | England / Wales | 94 | **2.01x** |
| 9 | Kamil Glik + Saleh Al-Shehri | Poland / Saudi Arabia | 85 | **2.00x** |
| 10 | Weston McKennie + Jurrien Timber | United States / Netherlands | 66 | **2.00x** |
| 11 | Nicolás Otamendi + Nestor Araujo | Argentina / Mexico | 96 | **1.98x** |
| 12 | Kamil Glik + Abdulelah Al-Malki | Poland / Saudi Arabia | 85 | **1.98x** |
| 13 | Krystian Bielik + Abdulelah Al-Malki | Poland / Saudi Arabia | 85 | **1.96x** |
| 14 | Virgil van Dijk + Weston McKennie | Netherlands / United States | 66 | **1.94x** |
| 15 | Richarlison + Vanja Milinković-Savić | Brazil / Serbia | 78 | **1.92x** |
