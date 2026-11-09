# Fresh jobs and referral paths

CareerOS now has two direct daily workflows in the main navigation.

## Fresh jobs

`/jobs?view=fresh` shows matched, non-ruled-out roles with a source publication
(or republication) date in the last 24 hours. One-hour and seven-day views use
the same rule. Results sort by that source date, independently of import time;
there is no implicit minimum score. Unknown eligibility remains labeled for review.
Explicit failures remain excluded unless the user changes the eligibility filter.

Source dates are provider assertions, not independent proof of the original launch.
For example, Ashby's public API defines `publishedAt` as the last publication time.
Unknown dates and future timestamps are excluded from timed views. The existing
matches view still includes roles whose publication date is unknown. Older initial
imports are never represented as newly posted jobs.

Monitoring is local polling. The app and worker must remain running and awake.
Public employer feeds default to 15-minute polling; stricter source limits take
precedence. Coverage, actual observations, failures and next due checks remain
visible in Monitoring. There is no continuous LinkedIn or Handshake scraping and
no guarantee that a provider exposes a posting the minute it is created.

Matching v8 also recognizes explicit non-US regions such as Europe Only and
keeps nursing-consultant titles out of generic business-consulting lanes. Explicit
custom clinical lanes continue to work; mixed US/international locations retain
the US option. Explicit exclusions for candidates requiring future sponsorship are
recognized without inferring the candidate’s status. Review reasons and source
quotes appear before the referral or application actions. Rescore existing
matches after upgrading.

## Referrals

Every role links directly to `/referrals?job_id=…`; an application is not required.
The workspace offers company-specific alumni, employee and public referral-post
searches plus BU's official networking directory. These are research handoffs,
not discovered or verified people and not promises of referrals.

Save a real person, their source/profile, relationship, possible introduction,
and notes. Existing contacts can be reused only for the same employer. A unique
job/contact pair prevents repeated form submissions duplicating the path. Saved
and tracked roles remain available when closed or ruled out by later matching.

Prepare a private request using the exact role URL and a relevant verified project.
Unverified projects are excluded. The request makes no claim that the person knows
the candidate, is an alumnus or will refer them. Drafts are editable and stored
with the existing private outreach infrastructure. Saving a draft does not change
a path's status. Contacted, replied, requested and referred states are explicitly
recorded by the user; the app has no automatic send action.

Migration 0015 adds one table and leaves existing contacts, applications and
profile facts intact. Back up before migration. The tests cover migration parity,
source-time ordering, time boundaries, unknown eligibility, company scoping,
duplicate submissions, private drafts, edits, CSRF and safe rendering.

## Primary references

- [Ashby public posting API](https://developers.ashbyhq.com/docs/public-job-posting-api)
- [BU Connects](https://www.bu.edu/alumni/career/buconnects/): official networking directory
- [LinkedIn student networking](https://students.linkedin.com/): alumni and mutual-contact research
