"""chunk_text is pure, and it is where bad retrieval starts: a chunk that is a
bare heading retrieves for everything, one that swallowed three jobs for nothing."""

from jobsearch.services.resume_chunks import MAX_CHARS, MIN_CHARS, chunk_text

RESUME = """Lukasz Wasyleczko
Senior Software Engineer

EXPERIENCE

{experience}

EDUCATION

BSc Computer Science, 2014
""".format(experience="Backend developer at Acme. " * 20)


def test_splits_on_blank_lines_and_keeps_sections_whole():
    chunks = chunk_text(RESUME)

    assert any("Backend developer at Acme." in chunk for chunk in chunks)
    assert all(chunk == chunk.strip() for chunk in chunks)
    assert "" not in chunks


def test_runt_blocks_merge_into_the_previous_chunk():
    # "EDUCATION" alone would retrieve for any posting; it must ride along with
    # either the block before or after it
    chunks = chunk_text(RESUME)

    assert "EDUCATION" not in chunks
    assert any("EDUCATION" in chunk and "BSc Computer Science" in chunk for chunk in chunks)


def test_oversized_block_is_split_under_the_cap():
    huge = "\n".join(f"- delivered project number {n} on time" for n in range(200))

    chunks = chunk_text(huge)

    assert len(chunks) > 1
    assert all(len(chunk) <= MAX_CHARS for chunk in chunks)


def test_short_resume_stays_a_single_chunk():
    assert chunk_text("Python developer, 5 years.") == ["Python developer, 5 years."]
    assert MIN_CHARS < MAX_CHARS


def test_blank_resume_produces_no_chunks():
    assert chunk_text("\n\n   \n") == []
