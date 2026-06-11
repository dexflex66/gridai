# Session State

## DONE (verified)

_To be filled after run with real numbers._

## IN PROGRESS

- Day 1 build: Layer 1 simulation core

## NEXT

- Day 2: tune scenarios, add AEMO 2012 Victorian load profile, lock headline numbers
- Day 3-4: Band SDK integration, four agents

## VERIFIED NUMBERS

_To be filled after real run._

## KNOWN ISSUES

_None yet._

## DO NOT

- Do not build a React/websocket dashboard; Layer 3 is precomputed JSON to standalone HTML
- Do not add a full power-flow solver; linear voltage approximation is correct for this layer
- Do not make all agents homogeneous by default; heterogeneity is the intellectual core
- Do not weaken test assertions to force green; fix the model instead
- Do not add Band SDK in Layer 1; that is Layer 2
