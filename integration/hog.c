#define _GNU_SOURCE

#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <signal.h>
#include <limits.h>

static int term_requested = 0;

void sig_handler(int signo)
{
	if (signo == SIGTERM) {
		term_requested = 1;
	}
}

int main(int argc, char* argv[]) {
	if (signal(SIGTERM, sig_handler) == SIG_ERR) {
		perror("register SIGTERM handler");
		return 1;
	}

	long hog_max;
	if (argc <= 1) {
		hog_max = LONG_MAX;
	} else {
		hog_max = strtol(argv[1], NULL, 10);
	}

	if (hog_max == 0) {
		fprintf(stdout, "invalid hog max: %s\n", argv[1]);
		return 1;
	}

	fprintf(stdout, "hog up to %ld\n", hog_max);
	fflush(stdout);

	sleep(2);

	long page_size = sysconf(_SC_PAGESIZE);
	long hogged = 0;

	unsigned long i = 0;

	while(1) {
		if (term_requested > 0) {
			fprintf(stdout, "exit: SIGTERM\n");
			fflush(stdout);
			return 0;
		}

		if (hogged > hog_max) {
			fprintf(stdout, "done hogging\n");
			sleep(2);
			continue;
		}

		if ((++i % 1000) == 0) {
			// Sleep for a little while every once in a while
			sleep(0.5);
		}

		char* tmp = (char*) malloc(page_size);

		if (tmp) {
			tmp[0] = 0;
		}

		hogged += page_size;
	}

	return 0;
}
