/**
 * Logger for KiCAD MCP server
 */

import { existsSync, mkdirSync, appendFileSync } from 'fs';
import { join } from 'path';
import * as os from 'os';

// Log levels
type LogLevel = 'error' | 'warn' | 'info' | 'debug';

// Default log directory
const DEFAULT_LOG_DIR = join(os.homedir(), '.kicad-mcp', 'logs');

/**
 * Logger class for KiCAD MCP server
 */
class Logger {
  private logLevel: LogLevel = 'info';
  private logDir: string = DEFAULT_LOG_DIR;
  
  /**
   * Set the log level
   * @param level Log level to set
   */
  setLogLevel(level: LogLevel): void {
    this.logLevel = level;
  }
  
  /**
   * Set the log directory
   * @param dir Directory to store log files
   */
  setLogDir(dir: string): void {
    this.logDir = dir;
    
    // Ensure log directory exists
    if (!existsSync(this.logDir)) {
      mkdirSync(this.logDir, { recursive: true });
    }
  }
  
  /**
   * Log an error message
   * @param message Message to log
   */
  error(message: string): void {
    this.log('error', message);
  }
  
  /**
   * Log a warning message
   * @param message Message to log
   */
  warn(message: string): void {
    if (['error', 'warn', 'info', 'debug'].includes(this.logLevel)) {
      this.log('warn', message);
    }
  }
  
  /**
   * Log an info message
   * @param message Message to log
   */
  info(message: string): void {
    if (['info', 'debug'].includes(this.logLevel)) {
      this.log('info', message);
    }
  }
  
  /**
   * Log a debug message
   * @param message Message to log
   */
  debug(message: string): void {
    if (this.logLevel === 'debug') {
      this.log('debug', message);
    }
  }
  
  /**
   * Log a message with the specified level
   * @param level Log level
   * @param message Message to log
   */
  private log(level: LogLevel, message: string): void {
    const timestamp = new Date().toISOString();
    const formattedMessage = `[${timestamp}] [${level.toUpperCase()}] ${message}`;
    
    // Log to console
    switch (level) {
      case 'error':
        console.error(formattedMessage);
        break;
      case 'warn':
        console.warn(formattedMessage);
        break;
      case 'info':
      case 'debug':
      default:
        console.log(formattedMessage);
        break;
    }
    
    // Log to file
    try {
      // Ensure log directory exists
      if (!existsSync(this.logDir)) {
        mkdirSync(this.logDir, { recursive: true });
      }
      
      const logFile = join(this.logDir, `kicad-mcp-${new Date().toISOString().split('T')[0]}.log`);
      appendFileSync(logFile, formattedMessage + '\n');
    } catch (error) {
      console.error(`Failed to write to log file: ${error}`);
    }
  }
}

// Create and export logger instance
export const logger = new Logger();
