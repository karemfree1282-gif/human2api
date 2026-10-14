package dev.human2api.companion;

import org.junit.Test;
import static org.junit.Assert.*;

public class CompanionSecurityTest {
    @Test
    public void testDefaultPortAndSessionTtl() {
        assertEquals(18765, CompanionService.BRIDGE_PORT);
        assertEquals(300_000L, CompanionService.SESSION_TTL_MS);
    }
}
