package tqm

import (
	"strings"
	"list"
	"time"
)

#tracker: {
	name!: string
	url!: string | [...string] & list.MinItems(1)
	seedDays?:    number & >0
	ratio?:       number & >0
	minSeedDays?: number & >0
}

#trackers: [...#tracker] & list.MinItems(1)
#tag: {
	name!: string
	mode:  *"full" | "add" | "remove"
	update!: [...string] & list.MinItems(1)
}

clients: qb: {
	download_path: "/data/downloads/torrents/complete"
	enabled:       true
	filter:        "default"
	type:          "qbittorrent"
	url:           "http://qbittorrent.default.svc.cluster.local"
}

#orphan: {
	grace_period?: string & time.Duration()
	ignore_paths?: [...string]
}

filters: [string]: {
	bypassIgnoreIfUnregistered?: bool
	MapHardlinksFor: [..."retag" | "clean"] // ?

	tag: [...#tag]
	remove: [...string]
	orphan?: #orphan
	ignore: [...string]
}

bypassIgnoreIfUnregistered: true

filters: default: {
	MapHardlinksFor: ["retag", "clean"]
	ignore: [
		"IsTrackerDown()",
		"Downloaded == false",
		"SeedingHours < 26",
		"HardlinkedOutsideClient == true",
		"Label startsWith \"music\"",
		// Protect unlinked torrents until minSeedDays is met (grace period before removal)
		for t in #trackers if t.minSeedDays != _|_ {
			"HasAllTags(\"site:\(t.name)\", \"not-linked\") && SeedingDays < \(t.minSeedDays)"
		},
	]
	orphan: {
		grace_period: "1h"
		ignore_paths: [
			"/data/downloads/torrents/complete/music",
			"/data/downloads/torrents/complete/uploads",
			"/data/downloads/torrents/complete/manual",
		]
	}
}

filters: default: tag: [
	{name: "added:1d", update: ["AddedDays < 7"]},
	{name: "added:7d", update: ["AddedDays >= 7 && AddedDays < 14"]},
	{name: "added:14d", update: ["AddedDays >= 14 && AddedDays < 30"]},
	{name: "added:30d", update: ["AddedDays >= 30 && AddedDays < 180"]},
	{name: "added:180d", update: ["AddedDays >= 180"]},
	{name: "tracker-down", update: ["IsTrackerDown()"]},
	{name: "unregistered", update: ["IsUnregistered()"]},
	{
		name: "not-linked"
		let cats = [for u in ["sonarr-imported", "radarr-imported", "cross-seed", "sonarr", "radarr"] {"\"\(u)\""}]
		update: [
			"HardlinkedOutsideClient == false",
			"Label in [\(strings.Join(cats, ","))]",
		]
	},
	{
		name:   "not-linked"
		mode:   "remove"
		update: ["HardlinkedOutsideClient == true"]
	},

	for t in #trackers {
		name: "site:\(t.name)"
		if (t.url & string) != _|_ {
			update: ["TrackerName == \"\(t.url)\""]
		}
		if (t.url & [...string]) != _|_ {
			let urls = [for u in t.url {"\"\(u)\""}]
			update: ["TrackerName in [\(strings.Join(urls, ", "))]"]
		}
	},

	for t in #trackers
	if t.minSeedDays != _|_ {
		name: "hnr"
		_filter: [...string]
		if (t.url & string) != _|_ {
			_filter: ["TrackerName == \"\(t.url)\""]
		}
		if (t.url & [...string]) != _|_ {
			let urls = [for u in t.url {"\"\(u)\""}]
			_filter: ["TrackerName in [\(strings.Join(urls, ", "))]"]
		}
		update: list.Concat([
			_filter,
			["SeedingDays < \(t.minSeedDays)"],
		])
	},
]

filters: default: remove: [
	"IsUnregistered()",
	"HasAllTags(\"not-linked\") && SeedingDays > 14",
	"Downloaded == false && AddedDays > 7",

	for t in #trackers if t.seedDays != _|_ || t.ratio != _|_ {
		if t.seedDays != _|_ && t.ratio != _|_ {
			"HasAllTags(\"site:\(t.name)\") && (Ratio > \(t.ratio) || SeedingDays >= \(t.seedDays))"
		}
		if t.seedDays != _|_ && t.ratio == _|_ {
			"HasAllTags(\"site:\(t.name)\") && SeedingDays >= \(t.seedDays)"
		}
		if t.seedDays == _|_ && t.ratio != _|_ {
			"HasAllTags(\"site:\(t.name)\") && Ratio > \(t.ratio)"
		}
	},

	for t in #trackers if t.minSeedDays != _|_ {
		"HasAllTags(\"site:\(t.name)\", \"not-linked\") && SeedingDays >= \(t.minSeedDays)"
	},
]
