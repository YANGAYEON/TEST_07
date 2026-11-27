// src/main/java/com/project/App.java
package com.project;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

@SpringBootApplication
@Controller
public class App {
    public static void main(String[] args) {
        SpringApplication.run(App.class, args);
    }

    @GetMapping("/")
    public String index() {
        return "index";
    }

    /** 업무 도식화 도구 (고객 설명용 / 개발자 설명용 흐름도) */
    @GetMapping({"/diagram", "/diagram/"})
    public String diagram() {
        return "redirect:/diagram/index.html";
    }
}
