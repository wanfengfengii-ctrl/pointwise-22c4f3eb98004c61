import argparse
import json
from pathlib import Path

from errors import ArchiveError, EvidenceError, RetiredRecording, SlotReplyLost, UnknownRecording, UnknownVolume
from inspection.register import list_shift_entries
from inspection.shifts import reconcile_shift
from pickup.read import read_volume, read_with_evidence
from recode.receipts import RecodeReceipt, load_first_receipt
from recode.requests import RecodeRequest, submit_recode
from recording.channels import ChannelStripe
from recording.ingest import accept_recording
from recording.retirement import retire_recording
from recording.sources import load_readable_recording, load_recording_provenance
from storage import ArchiveStore
from volume.catalog import get_verified_volume
from volume.seal import seal_volume


def _prepare_recording(store, sample):
    recording_id, volume_id = sample['recording_id'], sample['volume_id']
    channels = tuple(ChannelStripe(item['id'], bytes(item['values']), item['origin']) for item in sample['channels'])
    try:
        with store.catalog() as db:
            load_recording_provenance(db, recording_id)
    except UnknownRecording:
        accept_recording(store, recording_id, channels)
    try:
        with store.catalog() as db:
            volume = get_verified_volume(db, volume_id)
    except UnknownVolume:
        volume = seal_volume(store, recording_id, volume_id, sample['initial'])
    if volume.recording_id != recording_id:
        raise EvidenceError('demo volume belongs to a different recording')
    try:
        with store.catalog() as db:
            load_readable_recording(db, recording_id)
    except RetiredRecording:
        return
    retire_recording(store, recording_id, volume_id)


def _record_shift(store, shift_id, volume_id, request_id=None):
    with store.catalog() as db:
        for entry in list_shift_entries(db):
            if (entry.shift_id, entry.volume_id, entry.request_id) == (shift_id, volume_id, request_id):
                return entry
    return reconcile_shift(store, shift_id, volume_id, request_id).entry


def _print_scenario(sample, paused, pickup, evidence, receipt, shift):
    actual = {'stripes': [list(stripe) for stripe in pickup.stripes], 'origins': [p.origin for p in pickup.provenance]}
    expected = {'stripes': [[7], [11], [13]], 'origins': [item['origin'] for item in sample['channels']]}
    downstream = {
        'slots': [list(payload) for payload in evidence.payloads], 'basis': list(evidence.basis),
        'status': shift.status, 'original_receipt': shift.receipt_id == receipt.receipt_id,
    }
    expected_downstream = {'slots': [[11], [13], [12]], 'basis': [2, 4, 3], 'status': 'done', 'original_receipt': True}
    if paused is not None and (paused.stripes != pickup.stripes or paused.provenance != pickup.provenance):
        raise EvidenceError('demo pickup changed after the pause')
    if actual != expected or downstream != expected_downstream:
        raise EvidenceError('demo results differ from the waveform sample oracle')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'V4', 'input': sample, 'expected': expected, 'actual': actual,
        'downstream_expected': expected_downstream, 'downstream_actual': downstream,
        'code_paths': ['recode/apply.py', 'pickup/read.py', 'volume/slots.py', 'inspection/shifts.py'],
        'oracle': 'Hand XOR: B = 11, C = 13, A XOR B = 12. Original positions and origins follow the sample.',
    }, ensure_ascii=False, sort_keys=True))


def run_demo(root: Path) -> None:
    sample = json.loads(Path(__file__).with_name('demo-waveforms.json').read_text(encoding='utf-8'))
    store = ArchiveStore(root)
    _prepare_recording(store, sample)
    volume_id, request_id, target = sample['volume_id'], sample['request_id'], sample['target']
    _record_shift(store, 'demo-initial', volume_id)
    with store.catalog() as db:
        prior = load_first_receipt(db, request_id)

    def lose_first_reply(event):
        if event.phase == 'after':
            raise SlotReplyLost('demo lost the committed slot reply')

    paused = None
    if prior is None:
        progress = submit_recode(store, volume_id, request_id, target, on_boundary=lose_first_reply)
        if isinstance(progress, RecodeRequest):
            store = ArchiveStore(root)
            paused = read_volume(store, volume_id)
            entry = _record_shift(store, 'demo-pending', volume_id, request_id)
            print(json.dumps({'status': entry.status, 'basis': entry.basis, 'generations': entry.generations}))
    receipt = submit_recode(store, volume_id, request_id, target)
    if not isinstance(receipt, RecodeReceipt):
        raise EvidenceError('demo did not obtain a completed receipt')
    pickup, evidence = read_with_evidence(store, volume_id)
    shift = _record_shift(store, 'demo-complete', volume_id, request_id)
    if prior is None:
        _print_scenario(sample, paused, pickup, evidence, receipt, shift)
    print(json.dumps({
        'volume': pickup.volume_id, 'original': [list(stripe) for stripe in pickup.stripes],
        'origins': [origin.origin for origin in pickup.provenance], 'actual_basis': evidence.basis,
        'physical_slots': [list(payload) for payload in evidence.payloads],
        'receipt_id': receipt.receipt_id, 'receipt_target': receipt.target, 'registered_status': shift.status,
    }, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description='Run the waveform archive handoff sample')
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    try:
        run_demo(args.root)
    except ArchiveError as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
