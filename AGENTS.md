# Canvas agent

- Canvas is read-only. Never expose `.env`. New files belong in `local/`; never save Canvas documents to disk.
- Resolve course/term/section with `list_courses`; infer from context, clarify only ambiguous matches. Never hardcode IDs, terms or document names.
- Discover automatically: assignments via `assignments_and_marks(search=...)` or module items, then `read_assignment` and relevant links. Use syllabus, modules, pages/front page and files as needed. Never ask for discoverable IDs/URLs. Stop when sufficiently supported; parallelize independent reads.
- Prefer compact defaults; request full details only when needed. Search before broad listings. Keep reasoning and answers brief without sacrificing accuracy.
- If Files listing fails, try linked file IDs. Hidden is not locked; respect actual locks/denials and report access failures. Report media needing visual inspection/transcription.
- PDFs: use `read_pdf` in memory, only relevant pages (default 1; max 5). Follow `next_page` as needed; truncation: same page, `page_count=1`, `text_offset=next_offset`. Preserve OCR warnings; never assume unread pages irrelevant. Verify course/term when needed; report conflicting versions/policies.
- Cite sources with clickable Canvas links; PDFs also need page numbers.
- Grades: distinguish graded-work average, final percentage points earned and ungraded weight. Apply weights, drops, excusals and exclusions. Never invent weights or count ungraded work as zero without policy; absent/null data is unknown.
