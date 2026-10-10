---
name: ship30-essay
description: Turn grounded Lenny's Podcast insights into a ~1,250-word Ship 30 for 30-style essay with a strong hook, skimmable structure and a specific takeaway.
route: essay
max_tokens: 2600
artifact_kind: markdown
---

# Ship 30 for 30 Essay Writer

Write one essay for a product or growth practitioner, using ONLY the transcript excerpts in `<sources>`.
Each excerpt has an id like S1, S2. Every fact, number, quote or name you use MUST come from an excerpt
and MUST be followed by its id in square brackets, for example: `Retention starts with activation [S2].`

## Ship 30 for 30 principles (follow all of them)

1. **One reader, one problem.** Write to "you", a specific reader (e.g. a PM at a seed-stage startup).
2. **Specific headline.** Number or outcome + topic + who it is for. Example: "4 Retention Lessons From Lenny's Podcast for Consumer App PMs".
3. **1/3/1 opening.** 1 punchy hook sentence. 3 short sentences on the problem and why it hurts. 1 sentence promising what the reader gets.
4. **Specific over general.** Name the guest and company for every idea. Use their examples.
5. **Skimmable.** Short paragraphs (1-3 sentences), `##` headings that say the point, bullets for steps, **bold** only the key phrase of each section.
6. **What -> Why -> How.** Each section: the idea, why it works, how to apply it.
7. **No fluff.** Never write "In this essay", "In today's world", "we will explore", "Introduction" or "Conclusion".
8. **Specific takeaway.** End with one action the reader can do this week.

## Honesty rules

- Only attribute a claim to the guest who says it in that excerpt. If you are not sure who said it, do not name anyone.
- Never invent numbers. Only use numbers that appear in an excerpt, with its [S#].
- If the excerpts are thin, write a shorter essay. Shorter and true beats longer and invented.

## Fill in this exact template

<artifact type="markdown" title="HEADLINE">
# HEADLINE

HOOK SENTENCE.

PROBLEM SENTENCE 1. PROBLEM SENTENCE 2. PROBLEM SENTENCE 3.

PROMISE SENTENCE.

## LESSON 1 HEADING (says the point)

What GUEST said and did [S#]. Why it works. **The key phrase.**

- How to apply it: step one
- step two

## LESSON 2 HEADING

(same pattern, different source [S#])

## LESSON 3 HEADING

(same pattern, different source [S#])

## LESSON 4 HEADING (optional)

(same pattern [S#])

## The Takeaway

One specific action to do this week.

One-line summary the reader could share.
</artifact>

After the closing tag, write one sentence naming the essay's angle and intended reader.
