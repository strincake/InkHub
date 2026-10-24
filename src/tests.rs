use crate::scheduler::*;

#[test]
fn completion_of_exited_replacement_clears_old_key_focus() {
    let mut s = setup();
    s.sources[0].min_ms = 0;
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    s.update("b", 1).unwrap();
    let frame = s.next(1).unwrap();
    s.remove("b");
    s.complete(frame, 2);
    assert_eq!(s.key_target(2), None);
}

#[test]
fn own_update_does_not_hide_higher_priority_candidate() {
    let mut s = setup();
    s.sources[0].min_ms = 0;
    s.sources[1].priority = 1;
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    s.update("b", 1).unwrap();
    s.update("a", 2).unwrap();
    assert_eq!(s.next(2).unwrap().id, "b");
}

#[test]
fn hold_timeout_does_not_defeat_minimum_tenure() {
    let mut s = setup();
    s.sources[0].min_ms = 5000;
    s.sources[0].hold_ms = 1000;
    s.sources[1].priority = 5;
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    s.update("b", 100).unwrap();
    assert!(s.next(1001).is_none());
    assert_eq!(s.next(5000).unwrap().id, "b");
}

#[test]
fn replacement_boost_ends_only_on_actual_other_source_completion() {
    let mut s = setup();
    s.sources[0].min_ms = 0;
    s.sources[0].hold_ms = 10;
    s.sources[0].boost = Some(Boost {
        priority: 1,
        until: None,
        until_replaced: true,
    });
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    s.update("b", 1).unwrap();
    let next = s.next(11).unwrap();
    assert!(s.sources[0].boost.is_some());
    s.complete(next, 12);
    assert!(s.sources[0].boost.is_none());
}
fn source(id: &str, p: u8) -> Source {
    Source::new(id.into(), id.into(), p)
}
fn setup() -> Scheduler {
    let mut s = Scheduler::default();
    s.add(source("a", 3));
    s.add(source("b", 3));
    s
}
fn shown(s: &mut Scheduler, t: u64) {
    let x = s.next(t).unwrap();
    s.complete(x, t);
}

#[test]
fn empty_shows_immediately() {
    let mut s = setup();
    s.update("a", 0).unwrap();
    assert_eq!(s.next(0).unwrap().id, "a");
}
#[test]
fn equal_newer_waits_for_minimum() {
    let mut s = setup();
    s.sources[0].min_ms = 5000;
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    s.update("b", 1000).unwrap();
    assert!(s.next(1000).is_none());
    assert_eq!(s.next(5000).unwrap().id, "b");
}
#[test]
fn own_update_does_not_reset_tenure() {
    let mut s = setup();
    s.sources[0].min_ms = 5000;
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    s.update("a", 3000).unwrap();
    shown(&mut s, 3000);
    s.update("b", 4000).unwrap();
    assert_eq!(s.next(5000).unwrap().id, "b");
}
#[test]
fn bypass_is_not_priority_permission() {
    let mut s = setup();
    s.sources[0].priority = 1;
    s.sources[1].bypass = true;
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    s.update("b", 1).unwrap();
    assert!(s.next(1).is_none());
}
#[test]
fn bypass_skips_minimum_but_obeys_global_gate() {
    let mut s = setup();
    s.sources[1].priority = 1;
    s.sources[1].bypass = true;
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    s.update("b", 1).unwrap();
    s.preempt = false;
    assert!(s.next(1).is_none());
    s.preempt = true;
    assert_eq!(s.next(1).unwrap().id, "b");
}
#[test]
fn expired_task_cannot_win() {
    let mut s = setup();
    s.sources[0].ttl_ms = 100;
    s.update("a", 0).unwrap();
    assert!(s.next(101).is_none());
}
#[test]
fn source_timeout_yields_to_lower() {
    let mut s = setup();
    s.sources[0].priority = 1;
    s.sources[0].hold_ms = 100;
    s.sources[0].min_ms = 0;
    s.update("a", 0).unwrap();
    s.update("b", 0).unwrap();
    shown(&mut s, 0);
    assert_eq!(s.next(101).unwrap().id, "b");
}
#[test]
fn own_update_renews_display_timeout() {
    let mut s = setup();
    s.sources[0].hold_ms = 100;
    s.sources[0].min_ms = 0;
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    s.update("a", 80).unwrap();
    shown(&mut s, 80);
    s.update("b", 81).unwrap();
    s.sources[1].priority = 5;
    assert!(s.next(150).is_none());
    assert_eq!(s.next(181).unwrap().id, "b");
}
#[test]
fn live_revision_does_not_return_but_unseen_revision_does() {
    let mut s = setup();
    s.sources[0].min_ms = 0;
    s.sources[1].hold_ms = 100;
    s.sources[1].min_ms = 0;
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    s.update("b", 1).unwrap();
    shown(&mut s, 1);
    assert!(s.next(102).is_none());
    s.update("a", 103).unwrap();
    assert_eq!(s.next(103).unwrap().id, "a");
}
#[test]
fn persistent_falls_back_after_foreground_expires() {
    let mut s = setup();
    s.sources[0].persistent = true;
    s.sources[0].min_ms = 0;
    s.sources[1].hold_ms = 100;
    s.sources[1].min_ms = 0;
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    s.update("b", 1).unwrap();
    shown(&mut s, 1);
    assert_eq!(s.next(102).unwrap().id, "a");
}
#[test]
fn stale_completion_does_not_restore_exited_source() {
    let mut s = setup();
    s.update("a", 0).unwrap();
    let x = s.next(0).unwrap();
    s.remove("a");
    s.complete(x, 1);
    assert!(s.current.is_none());
}
#[test]
fn pending_new_revision_survives_old_completion() {
    let mut s = setup();
    s.update("a", 0).unwrap();
    let x = s.next(0).unwrap();
    s.update("a", 1).unwrap();
    s.complete(x, 2);
    assert_eq!(s.next(2).unwrap().revision, 2);
}
#[test]
fn boost_expires_and_never_mutates_base_priority() {
    let mut s = setup();
    s.sources[0].boost = Some(Boost {
        priority: 1,
        until: Some(100),
        until_replaced: false,
    });
    assert_eq!(s.sources[0].effective(50), 1);
    assert_eq!(s.sources[0].effective(100), 3);
}
#[test]
fn keys_stay_on_actual_display_until_completion() {
    let mut s = setup();
    s.sources[0].min_ms = 0;
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    s.update("b", 1).unwrap();
    let x = s.next(1).unwrap();
    assert_eq!(s.key_target(1), Some("a".into()));
    s.complete(x, 2);
    assert_eq!(s.key_target(2), Some("b".into()));
}
#[test]
fn expired_display_receives_no_keys() {
    let mut s = setup();
    s.sources[0].ttl_ms = 100;
    s.update("a", 0).unwrap();
    shown(&mut s, 0);
    assert_eq!(s.key_target(101), None);
}
