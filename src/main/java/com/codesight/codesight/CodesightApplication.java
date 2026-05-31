package com.codesight.codesight;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.EnableAsync;

import com.codesight.codesight.common.config.StorageProperties;

@SpringBootApplication
@EnableAsync
@EnableConfigurationProperties(StorageProperties.class)
public class CodesightApplication {

	public static void main(String[] args) {
		SpringApplication.run(CodesightApplication.class, args);
	}

}