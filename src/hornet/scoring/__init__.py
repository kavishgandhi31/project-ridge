"""Scoring engine — computes macro dimension scores and composites.

This package contains the pure-computation scoring engine (no DB
dependency). The engine takes ``list[Observation]`` and
``list[EventRecord]`` as input and produces ``ScoreResult`` objects.
An async orchestrator in ``runner.py`` wires DB repos to the engine
and persists the results.
"""
