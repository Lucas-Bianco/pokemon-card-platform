import type { Candidate } from "../api/types";

interface Props {
  candidates: Candidate[];
  onPick: (cardId: string) => void;
  onReject: () => void;
}

export default function CandidatePicker({ candidates, onPick, onReject }: Props) {
  return (
    <div className="picker">
      <ul className="candidates">
        {candidates.map((candidate) => (
          <li key={candidate.card_id}>
            <button onClick={() => onPick(candidate.card_id)}>
              {candidate.image_small && <img src={candidate.image_small} alt="" loading="lazy" />}
              <span className="candidate-text">
                <strong>{candidate.name}</strong>
                <span className="candidate-meta">
                  {candidate.set_name} · #{candidate.number}
                </span>
              </span>
              <span className="score">{(candidate.visual_score * 100).toFixed(0)}%</span>
            </button>
          </li>
        ))}
      </ul>
      <button className="reject" onClick={onReject}>
        None of these
      </button>
    </div>
  );
}
