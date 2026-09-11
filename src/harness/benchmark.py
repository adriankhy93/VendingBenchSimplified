"""Fixed-seed HTTP suite; never mix completion classes in score statistics."""
import argparse
import json
from pathlib import Path
import statistics
import time
from .runner import RunConfig, run

def suite(config, seeds=(0, 1, 2), agents=('idle', 'listed', 'negotiating')):
    if config.environment_name:
        raise ValueError('seed suites require generated scenarios; use vending-run --environment for a fixed saved environment')
    reports = []
    for agent in agents:
        episodes = []
        for seed in seeds:
            effective = RunConfig.model_validate(config.model_dump() | dict(agent=agent, seed=seed))
            directory, result = run(effective)
            episodes.append(dict(directory=str(directory), summary=result))
        completed = [e['summary'] for e in episodes if e['summary']['complete']]
        scores = [e['terminal']['score']['score_cents'] for e in completed]
        reports.append(dict(agent=agent, episodes=episodes, completion_rate=len(completed)/len(episodes),
                            score_mean_cents=statistics.mean(scores) if scores else None,
                            score_stdev_cents=statistics.pstdev(scores) if scores else None,
                            wall_seconds=sum(e['summary']['usage']['wall_seconds'] for e in episodes),
                            tokens=sum(e['summary']['usage']['input_tokens']+e['summary']['usage']['output_tokens'] for e in episodes)))
    return dict(config=config.model_dump(mode='json'), seeds=list(seeds), reports=reports)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--seeds', nargs='+', type=int, default=[0,1,2])
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    config = RunConfig.model_validate_json(Path(args.config).read_text()) if args.config else RunConfig()
    if args.smoke:
        config = RunConfig.model_validate(config.model_dump() | dict(scenario_id='smoke-v1', max_days=14, runtime_seconds=120))
    started = time.monotonic()
    report = suite(config, args.seeds)
    report['wall_seconds'] = time.monotonic() - started
    path = Path(config.artifact_dir) / f'suite-{time.time_ns()}.json'
    path.write_text(json.dumps(report, indent=2))
    print(path)

if __name__ == '__main__':
    main()
