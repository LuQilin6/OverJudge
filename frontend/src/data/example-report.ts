// Adapted from docs/examples/2026-10-25/outputs/runs/example_run/stages/B/results/20261025T052411.724132Z-4a2ce44f68f1/result.json. No final judgment is asserted.
import { reviewReportSchema } from '../api/contracts';
export const examplePlayers = [
  {
    "id": "tank",
    "label": "ROXY",
    "hero": "Mauga",
    "role": "Tank"
  },
  {
    "id": "dps1",
    "label": "KANEKI",
    "hero": "Reaper",
    "role": "Damage"
  },
  {
    "id": "dps2",
    "label": "PINEAPPLE",
    "hero": "",
    "role": "Damage"
  },
  {
    "id": "support1",
    "label": "MEWTWO",
    "hero": "Jetpack Cat",
    "role": "Support"
  },
  {
    "id": "support2",
    "label": "MMONK",
    "hero": "Kiriko",
    "role": "Support"
  }
];
export const exampleReport = reviewReportSchema.parse({
  "verdict": "inconclusive",
  "summary": "The footage supports a reconstruction of the fight, but this example has no final judgment assigning responsibility.",
  "fightSummary": "The reports reconstruct a doorway approach followed by central-lane combat, repeated low-health ROXY exchanges, movement toward a side room and a final doorway engagement.",
  "confidence": {
    "label": "low",
    "rationale": "This preview adapts a Stage B reconstruction. A final verdict and separate evidence check are not included in this example."
  },
  "evidence": [
    {
      "observation": "Reciprocal HUD notifications report SAVED BY KIRIKO (MMONK) for ROXY and SAVED MAUGA (ROXY) for Kiriko. The credited save is corroborated; its exact triggering effect and counterfactual survival are unknown.",
      "refs": [
        {
          "povId": "tank",
          "start": 10.0,
          "end": 11.0
        },
        {
          "povId": "support2",
          "start": 8.0,
          "end": 10.5
        }
      ]
    },
    {
      "observation": "ROXY is eliminated after the alive 17.0 sample and by 17.5. The tank death HUD and all four other reports corroborate displayed ALPHARI elimination credit. The tank citation ends at 18.0 but contains only the 17.5 image; this does not extend observed coverage. Full damage circumstances and overall outcome remain unknown.",
      "refs": [
        {
          "povId": "tank",
          "start": 16.0,
          "end": 17.5
        },
        {
          "povId": "tank",
          "start": 17.5,
          "end": 18.0
        },
        {
          "povId": "dps1",
          "start": 16.0,
          "end": 17.5
        },
        {
          "povId": "dps2",
          "start": 17.0,
          "end": 17.5
        },
        {
          "povId": "support1",
          "start": 15.0,
          "end": 17.5
        },
        {
          "povId": "support2",
          "start": 13.5,
          "end": 17.5
        }
      ]
    }
  ],
  "decisions": [],
  "players": [
    {
      "povId": "tank",
      "summary": "Fires at close opponent, loses health, briefly recovers and sees Kiriko save notification.",
      "status": "no_supported_mistake"
    },
    {
      "povId": "dps1",
      "summary": "Relocates near ice/stairs, then advances firing behind ROXY.",
      "status": "no_supported_mistake"
    },
    {
      "povId": "dps2",
      "summary": "Reloads, fires near ROXY and takes damage near 10.0; ability identity unknown.",
      "status": "no_supported_mistake"
    },
    {
      "povId": "support1",
      "summary": "Moves beneath walkway toward lane, then projects yellow shots toward clustered fight.",
      "status": "no_supported_mistake"
    },
    {
      "povId": "support2",
      "summary": "Alternates healing/throwing poses, approaches doorway and receives credited save notification for ROXY; projectile effects are incompletely resolved.",
      "status": "no_supported_mistake"
    }
  ],
  "coaching": [],
  "limitations": [
    "Example only: adapted from the checked-in Stage B reconstruction, not a completed verdict. Player status means no final finding is supplied in this preview.",
    "The human evidence audit is pending. Observations remain provisional.",
    "Only frames sampled every 0.5 seconds were inspected. Audio and team communications were not available.",
    "The complete fight outcome and subsequent objective ownership are unknown.",
    "Player and hero identities are source-reported, not independently verified."
  ]
});
