import type { Centering } from "../api/types";

interface Props {
  centering: Centering;
}

// PSA's own notation: whole share points, e.g. 55/45. The decimals live on the worst
// axis, where they matter because they sit next to the ± that qualifies them.
function ratio([a, b]: [number, number]): string {
  return `${Math.round(a)} / ${Math.round(b)}`;
}

/**
 * Presentation only. Every line here is worded to say what centering *rules out*:
 * a perfectly centred card is not a 10, it merely is not stopped from being one by
 * this criterion. Corners, edges and surface are never looked at, and neither is the
 * back — so the panel must not read as a grade.
 */
export default function CenteringPanel({ centering }: Props) {
  const { left_right, top_bottom, worst_axis, uncertainty, psa_cap, psa_cap_certain } = centering;

  const headline =
    psa_cap === null
      ? // Worse than every published band. Printing "null", or rounding down to the
        // lowest band we know of, would both be inventions.
        "Centering is outside PSA's published range"
      : `Centering allows up to PSA ${psa_cap}`;

  return (
    <section className="centering">
      <h3 className="centering-headline">
        {headline}
        {!psa_cap_certain && <span className="centering-flag"> — too close to call</span>}
      </h3>
      <p className="centering-sub">
        A ceiling, not a grade. PSA's threshold is “approximately” 55/45 and graders apply
        discretion, so even a settled reading is not a guarantee.
      </p>

      <dl className="centering-axes">
        <div>
          <dt>Left / right</dt>
          <dd>{ratio(left_right)}</dd>
        </div>
        <div>
          <dt>Top / bottom</dt>
          <dd>{ratio(top_bottom)}</dd>
        </div>
        <div className="axis-worst">
          <dt>Worst axis</dt>
          <dd>
            {worst_axis.toFixed(1)} ± {uncertainty.toFixed(1)}
          </dd>
        </div>
      </dl>

      {!psa_cap_certain && (
        <p className="centering-uncertain">
          {worst_axis.toFixed(1)} ± {uncertainty.toFixed(1)} share points straddles a band
          boundary, so this measurement cannot separate the two neighbouring grades.
        </p>
      )}

      <ul className="centering-caveats">
        <li>Front only — the back is never photographed, and PSA grades it separately.</li>
        <li>
          Centering is one of four criteria: corners, edges and surface are not assessed here.
        </li>
      </ul>
    </section>
  );
}
