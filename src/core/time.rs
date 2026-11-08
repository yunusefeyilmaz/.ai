//! UTC timestamps in the same format the Python CLI writes.

use chrono::{DateTime, Datelike, NaiveDateTime, SecondsFormat, TimeZone, Timelike, Utc};

/// Current time truncated to whole seconds (the on-disk contract has no subsecond).
pub fn now() -> DateTime<Utc> {
    Utc::now().with_nanosecond(0).unwrap_or_else(Utc::now)
}

/// `2026-11-07T12:34:56Z`
pub fn iso(value: Option<DateTime<Utc>>) -> String {
    value
        .unwrap_or_else(now)
        .to_rfc3339_opts(SecondsFormat::Secs, true)
}

/// Parse an ISO timestamp; naive values are interpreted as UTC, like Python.
pub fn parse_iso(value: &str) -> Option<DateTime<Utc>> {
    let text = value.trim();
    if text.is_empty() {
        return None;
    }
    if let Ok(parsed) = DateTime::parse_from_rfc3339(text) {
        return Some(parsed.with_timezone(&Utc));
    }
    for pattern in ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M:%S%.f"] {
        if let Ok(naive) = NaiveDateTime::parse_from_str(text, pattern) {
            return Some(Utc.from_utc_datetime(&naive));
        }
    }
    None
}

/// Minutes since `value`, or None when the timestamp cannot be parsed.
pub fn age_minutes(value: Option<&str>) -> Option<f64> {
    let value = value?;
    let parsed = parse_iso(value)?;
    Some((now() - parsed).num_seconds() as f64 / 60.0)
}

/// `20261107T123456Z` (archive file names).
pub fn compact_stamp(value: DateTime<Utc>) -> String {
    format!(
        "{:04}{:02}{:02}T{:02}{:02}{:02}Z",
        value.year(),
        value.month(),
        value.day(),
        value.hour(),
        value.minute(),
        value.second()
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip() {
        let stamp = iso(None);
        assert!(stamp.ends_with('Z'));
        assert!(parse_iso(&stamp).is_some());
    }

    #[test]
    fn naive_is_utc() {
        assert!(parse_iso("2026-01-02T03:04:05").is_some());
    }
}
