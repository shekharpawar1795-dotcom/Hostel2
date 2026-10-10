# HostelCare React feature mapping

Legend: **Wired** means a genuine React form/view is connected to the original FastAPI mutation handler. **Covered** means behavior is exercised via automated FastAPI HTTP tests. React browser, Netlify proxy, and photo-upload behavior still require live verification.

| Workflow | New React screen | Server code reused | Validation performed |
|---|---|---|---|
| URN/staff ID login, cookie sessions, login rate limiting | Login | `/login` via `/api/action/login` | API smoke |
| Forced password change | Password | `/profile/password` | API smoke |
| Five roles / hostel authorization | Five dashboards | `who`, `can_view`, `user_hostel_ids` | Original tests + API workflow |
| Preferred name/phone edits | Profile | `/profile` | Original tests |
| Student's assigned hostel/room | Dashboard | `student_room` | API workflow |
| New complaint, idempotency and category/priority | New complaint | `/student/new` | Original tests + API workflow |
| Photo evidence (private, max three, image validation) | New and detail | `/student/new`, `/photos/{id}` | Original tests (direct), proxy live test pending |
| Rector review/assign/classify/reject/verify/reopen | Detail | Rector action handler | Original tests + API workflow (assign) |
| Scoped Rector search/status filtering/pagination | Rector dashboard | React API filtering | Needs browser test |
| Worker accept/start/hold/resume/progress/complete | Detail | Staff action handler | Original tests + API workflow (accept/start/complete) |
| Student confirm/rating/reopen | Detail | Student verification handler | Original tests + API workflow (confirm) |
| Unstarted work -> Dean after 48h per cycle | Dean dashboard / detail | `process_due` and existing worker | Original tests |
| Unconfirmed eligible repair auto-close after 48h | Detail | `process_due` and existing worker | Original tests |
| Exceptional cases require Rector verification | Detail | Original server rules | Original tests |
| Dean directives | Detail | Dean directive handler | Original tests |
| Notifications and mark read | Notifications | Original handlers | API action wired |
| Hostel creation/archive/reactivate/delete unused | Admin dashboard | Original handlers | Original tests |
| Rooms, staff scopes, room allocations | Admin dashboard | Original handlers | API workflow |
| Individual temporary passwords / password resets | Admin credentials screen | Original handlers | API smoke |
| Up to 250 CSV student imports | Admin dashboard | Original handler | Existing handler retained; browser check pending |
| Audit trail, feedback, attachment listing | Complaint/admin pages | Existing SQLAlchemy queries | Original tests, API read |

**Netlify frontend cannot itself host FastAPI, on-disk SQLite, private local photos, or a permanently running 5-minute worker.** This edition preserves the existing backend externally rather than claiming Netlify-only hosting.
