package com.codesight.codesight.common.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "codesight.storage")
public record StorageProperties(String root) {
}
