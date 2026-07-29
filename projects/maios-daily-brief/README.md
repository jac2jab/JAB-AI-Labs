# MAIOS Daily Brief

## Purpose

The MAIOS Daily Brief reduces information overload by transforming incoming
emails and newsletters into a short, prioritized action brief.

## First Experiment

**User:** Jason Brockman

**Problem:** Too much time is spent reading, sorting, and mentally processing
AI newsletters, career emails, and other incoming information.

**Desired outcome:** A concise daily brief containing only the information
relevant to current goals.

## Version 0.1

The first prototype:

1. Reads structured sample email data from JSON.
2. Filters out low-priority content.
3. Sorts relevant items by priority.
4. Groups items by category.
5. Generates a Markdown daily brief.
6. Recommends several next actions.

## Run the prototype

```powershell
python generate_brief.py