# FLOPPI 0.5.0 - Hybrid Intelligence Engine

## Purpose

The engine combines historical indicator evidence into an explainable,
descriptive classification. It does not forecast prices, provide trade
instructions, or connect to brokers. The API labels the output as `DEMO`.

## Evidence model

| Family | Inputs | Rule |
|---|---|---|
| Trend | SMA 20/50, EMA 12/26 | SMA is preferred when available; EMA is a fallback and a consistency check. If SMA and EMA directions disagree, trend is internally conflicted and casts no directional vote. |
| Momentum | MACD/signal or histogram, RSI 14 | MACD and RSI are combined into one family. RSI above 55 is positive, below 45 is negative, and 45-55 is neutral. If MACD and RSI disagree, momentum casts no directional vote. |
| Price-volume | Latest close, cumulative VWAP | Close above VWAP is positive; close below VWAP is negative; equality or unavailable VWAP is neutral/unavailable. |

ATR 14 is reported as volatility context and as a percentage of latest close
when possible. It never casts a directional vote.

## Consensus policy

- At least two directional families are required.
- A tied directional split causes `status=abstain` and `bias=undetermined`.
- A majority below 80% is `provisional`.
- Agreement at or above 80% is `concordant`.
- `confidence_score` is only the raw agreement percentage among directional
  families. It is not a probability, calibrated confidence, or forecast.
- `evidence_coverage` reports the share of the three families with usable input.
- Internal disagreements are listed under `internal_conflicts`; disagreement
  between directional families is listed under `contradictory_families`.

## Endpoint

`GET /api/v1/analysis/hybrid?asset_id=<UUID>&timeframe=<timeframe>&limit=500`

Supported timeframes are `1m`, `5m`, `15m`, `1h`, `4h`, `1d`, and `1w`.
The endpoint returns the existing descriptive summary, including `summary.hybrid`,
plus `data_kind=DEMO` and `scope=descriptive_analysis_only`.

## Limitations

- The thresholds are transparent rule-based heuristics, not statistically
  calibrated weights.
- VWAP is cumulative over the requested candle sample; it does not infer
  exchange sessions.
- Correlated indicators are grouped, but method families are not guaranteed to
  be statistically independent.
- Data quality, missing history, provider differences, market regimes, and
  sample size can materially affect the descriptive output.
- A 100% automated audit result only means the configured automated checks
  passed. It is not a production certification or evidence of predictive skill.
