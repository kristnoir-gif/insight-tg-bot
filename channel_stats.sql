PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE channel_stats (
                channel_key TEXT PRIMARY KEY,
                title TEXT,
                analysis_count INTEGER DEFAULT 1,
                last_analyzed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            , subscribers INTEGER DEFAULT 0);
INSERT INTO channel_stats VALUES('okolozhizni','ОКОЛОЖИЗНИ',1,'2026-01-22 10:44:04',0);
INSERT INTO channel_stats VALUES('xeniawhore','Сопереживаю муравьям',1,'2026-01-22 10:47:25',0);
INSERT INTO channel_stats VALUES('uylaaaaa5','щелбан врагам кубани',1,'2026-01-22 10:49:08',0);
INSERT INTO channel_stats VALUES('lenanaaaaaososo','с каждым днем я становлюсь чуточку смешнее и нестабильнее',1,'2026-01-22 11:03:26',0);
INSERT INTO channel_stats VALUES('dmndradio','DMND RADIO / dmndwave',1,'2026-01-22 11:11:48',0);
COMMIT;
