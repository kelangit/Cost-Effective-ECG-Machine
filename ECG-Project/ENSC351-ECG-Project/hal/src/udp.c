// udp.c
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <pthread.h>
#include <string.h>

#include "udp.h"
#include "adc.h"

#define PORT 12345

static int sockfd = -1;
static pthread_t udp_thread;
static atomic_bool *running_flag = NULL;

// Remember the last client that asked for "send"
static struct sockaddr_in last_client;
static socklen_t last_client_len = 0;
static bool client_known = false;

// -----------------------------------------------------------------------------
// Called by ADC thread to send one ECG sample to the last "send" client
// -----------------------------------------------------------------------------
void udp_send_sample(float v)
{
    if (!client_known || sockfd < 0) {
        return; // no client yet or socket not ready
    }

    char buf[32];
    int len = snprintf(buf, sizeof(buf), "%.5f\n", v);
    if (len <= 0) return;

    (void)sendto(sockfd, buf, len, 0,
                 (struct sockaddr *)&last_client, last_client_len);
}

// -----------------------------------------------------------------------------
// Handle a single command
// -----------------------------------------------------------------------------
static void handle_command(char *userInput,
                           int sockfd,
                           struct sockaddr_in client_address,
                           socklen_t size)
{
    char reply[128];

    // Trim trailing newline(s)
    size_t len = strlen(userInput);
    while (len > 0 && (userInput[len-1] == '\n' || userInput[len-1] == '\r')) {
        userInput[--len] = '\0';
    }

    if (len == 0) {
        return;
    }

    if (strcmp(userInput, "send") == 0) {
        last_client     = client_address;
        last_client_len = size;
        client_known    = true;

        snprintf(reply, sizeof(reply), "OK: streaming ECG samples.\n");
        sendto(sockfd, reply, strlen(reply), 0,
               (struct sockaddr *)&client_address, size);
    } else if (strcmp(userInput, "stop") == 0) {
        // stop everything
        if (running_flag) {
            atomic_store(running_flag, false);
        }

        snprintf(reply, sizeof(reply), "Stopping server.\n");
        sendto(sockfd, reply, strlen(reply), 0,
               (struct sockaddr *)&client_address, size);

        if (sockfd >= 0) {
            shutdown(sockfd, SHUT_RDWR); // unblock recvfrom()
        }
    } else {
        snprintf(reply, sizeof(reply), "Unknown command. Use: send or stop\n");
        sendto(sockfd, reply, strlen(reply), 0,
               (struct sockaddr *)&client_address, size);
    }
}

// -----------------------------------------------------------------------------
// UDP listener thread
// -----------------------------------------------------------------------------
static void *udp_thread_listen(void *arg)
{
    (void)arg;

    struct sockaddr_in server_addr, client_addr;
    socklen_t client_len = sizeof(client_addr);
    char buffer[512];

    sockfd = socket(AF_INET, SOCK_DGRAM, 0);
    if (sockfd < 0) {
        perror("socket");
        return NULL;
    }

    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family      = AF_INET;
    server_addr.sin_addr.s_addr = INADDR_ANY;
    server_addr.sin_port        = htons(PORT);

    if (bind(sockfd, (struct sockaddr *)&server_addr,
             sizeof(server_addr)) < 0) {
        perror("bind");
        close(sockfd);
        sockfd = -1;
        return NULL;
    }

    while (atomic_load(running_flag)) {
        int n = recvfrom(sockfd, buffer, sizeof(buffer) - 1, 0,
                         (struct sockaddr *)&client_addr, &client_len);
        if (n < 0) {
            if (!atomic_load(running_flag)) break;
            perror("recvfrom");
            break;
        }

        buffer[n] = '\0';
        handle_command(buffer, sockfd, client_addr, client_len);
    }

    return NULL;
}

// -----------------------------------------------------------------------------
// Public API
// -----------------------------------------------------------------------------
void udp_init(atomic_bool *running)
{
    running_flag = running;
    pthread_create(&udp_thread, NULL, udp_thread_listen, NULL);
}

void udp_cleanup(void)
{
    if (sockfd >= 0) {
        shutdown(sockfd, SHUT_RDWR);  // unblock recvfrom()
    }

    pthread_join(udp_thread, NULL);

    if (sockfd >= 0) {
        close(sockfd);
        sockfd = -1;
    }
}
