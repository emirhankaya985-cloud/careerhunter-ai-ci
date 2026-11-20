# Hourly country discovery

The collector keeps the existing eight ATS boards and adds two verified public
Greenhouse boards per hour from Canonical, Datadog, Cloudflare, Elastic, MongoDB,
Grafana Labs and Adyen. All seven endpoints returned nonempty JSON on 2026-11-20.
Every extra board is revisited within four consecutive successful hourly runs.

The shortlist focuses on six countries per hour: US, DE and GB always, plus three
of 33 rotating targets. Every target appears within eleven consecutive hours.
The schedule uses absolute UTC hours, so midnight and DST do not reset coverage.
GitHub Actions can delay or skip scheduled runs; eleven hours is not a delivery SLA.

Targets (36): US, DE, GB, CA, CH, NL, AU, SE, DK, NO, FI, IE, FR, AT, BE, LU,
SG, JP, KR, NZ, AE, IL, TW, CZ, PL, EE, LT, LV, ES, PT, IT, IS, SI, SA, QA, TR.
These are practical research targets, not a salary ranking. Innovation context:
https://www.wipo.int/en/web/global-innovation-index/2026/index
Salary and sponsorship must be established for each actual vacancy.

Full board snapshots are scored, persisted and reconciled BEFORE filtering the
report. Never close jobs because their country is outside this hour's focus.
Existing alerts and CRM archival remain unchanged, preventing loss of relevant
remote jobs outside the focus. Unknown remote locations remain in the shortlist.

Each run report distinguishes observed location matches from profile score >=65
(non-senior). A zero is explicitly a source-coverage gap, not proof that the country
has no vacancies. Global/EMEA/remote labels are not allocated to all countries.
The seven global boards do not establish comprehensive coverage of all 36 targets.
Dedicated local/employer sources remain necessary where no country evidence exists.

Success measures: fresh relevant non-senior matches, eligibility evidence, verified
salary, owner-approved applications and real replies. Raw job count and technical
run success alone cannot establish recruitment success. No applications or emails
are sent by this change. No new paid service is used.

Validation: country coverage from every possible rotation offset, timezone and
midnight behavior, source revisit budget, honest country attribution, and personal
fit counts. Live acceptance still requires merged release, deployed Render commit,
a scheduled scan and its country report; local tests alone do not prove activation.
